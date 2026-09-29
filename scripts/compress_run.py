#!/usr/bin/env python3
"""
Песчаная куча из картинки -> GIF.

Пайплайн:
  1. Картинка (jpg/jpeg/png) укрупняется в "большие пиксели": берутся только целые
     квадраты b x b (неполные края отбрасываются), каждый усредняется в 1 пиксель.
     b подбирается автоматически так, чтобы результат был < 256 по большей стороне.
  2. Для каждого пикселя берутся R, G, B (0..255) и сдвигаются вправо на --shift бит
     (по умолчанию 5 -> значения 0..7). Это число песчинок в клетке, по одной куче на канал.
  3. Обычная модель песчаной кучи (Abelian sandpile): клетка с >= 4 песчинками
     обрушивается, отдавая по 1 песчинке четырём соседям. За край песчинки уходят.
  4. Анимация: 1 шаг = 3 подшага (R, затем G, затем B). В каждом подшаге
     обрушение делает ОДИН канал. Кадр записывается на каждом подшаге
     (см. --frame-every). Заканчиваем, когда все три кучи стабильны.

Расчёты идут на GPU через PyTorch (если есть CUDA), иначе на CPU.
Т.к. каналы независимы, все три считаются одним батчем [3,H,W], а
"поканальность" подшагов восстанавливается только при сборке кадров.

Использование:
    python sandpile_gif.py input.png -o out.gif
    python sandpile_gif.py photo.jpg --shift 4 --max-frames 400 --scale 3
"""
import argparse
import math
import sys

import numpy as np
import torch
from PIL import Image


def pixelate(img: Image.Image, max_size: int) -> np.ndarray:
    """Усреднение целых блоков b x b. Результат строго меньше max_size по обеим сторонам."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w, _ = arr.shape
    b = max(h, w) // max_size + 1  # гарантирует max(h, w) // b < max_size
    nh, nw = h // b, w // b
    if nh == 0 or nw == 0:
        raise ValueError("Картинка слишком мала для выбранного размера блока")
    arr = arr[: nh * b, : nw * b]  # отбрасываем неполные блоки на краях
    arr = arr.reshape(nh, b, nw, b, 3).mean(axis=(1, 3))
    print(f"Исходник {w}x{h}, блок {b}x{b} -> {nw}x{nh} пикселей")
    return np.rint(arr).astype(np.int32)  # [H, W, 3]


def topple(h: torch.Tensor):
    """Один параллельный шаг обрушения для всех каналов. h: int32 [3,H,W].
    Возвращает новое состояние или None, если всё стабильно."""
    t = h >> 2  # floor(h / 4): сколько раз клетка обрушивается
    if not bool(t.any()):
        return None
    new = h - (t << 2)
    new[:, 1:, :] += t[:, :-1, :]
    new[:, :-1, :] += t[:, 1:, :]
    new[:, :, 1:] += t[:, :, :-1]
    new[:, :, :-1] += t[:, :, 1:]
    return new  # песчинки, вышедшие за край, теряются


def to_frame(state: torch.Tensor, gain: float, scale: int) -> Image.Image:
    img = (state.float() * gain).clamp_(0, 255).to(torch.uint8)  # [3,H,W]
    if scale > 1:
        img = img.repeat_interleave(scale, dim=1).repeat_interleave(scale, dim=2)
    return Image.fromarray(img.permute(1, 2, 0).contiguous().cpu().numpy(), "RGB")


def main():
    p = argparse.ArgumentParser(description="Sandpile GIF из картинки")
    p.add_argument("input")
    p.add_argument("-o", "--output", default="sandpile.gif")
    p.add_argument("--raw", action="store_true", help="не укрупнять пиксели, рассыпать исходную картинку сразу")
    p.add_argument("--max-size", type=int, default=256, help="результат строго меньше этого (по стороне)")
    p.add_argument("--shift", type=int, default=5, help="сдвиг вправо для 0..255 (5 -> 0..7)")
    p.add_argument("--scale", type=int, default=0, help="увеличение пикселей в GIF (0 = авто, ~512 px)")
    p.add_argument("--max-frames", type=int, default=300, help="лимит кадров (лишние подшаги пропускаются)")
    p.add_argument("--frame-every", type=int, default=0, help="писать каждый N-й подшаг (0 = авто по max-frames)")
    p.add_argument("--duration", type=int, default=40, help="мс на кадр")
    p.add_argument("--hold", type=int, default=2000, help="мс задержки на последнем кадре")
    args = p.parse_args()

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Устройство:", dev)

    src = Image.open(args.input)
    if args.raw:
        # без укрупнения: рассыпаем исходные пиксели как есть
        pix = np.asarray(src.convert("RGB"), dtype=np.int32)
        print(f"Режим --raw: {pix.shape[1]}x{pix.shape[0]} пикселей без укрупнения")
        if pix.shape[0] * pix.shape[1] > 1024 * 1024:
            print("Внимание: большая картинка, рассыпание и GIF могут занять много времени и памяти")
    else:
        pix = pixelate(src, args.max_size)  # [H,W,3]
    H, W, _ = pix.shape
    h0 = torch.from_numpy(pix >> args.shift).permute(2, 0, 1).contiguous().to(dev)  # [3,H,W] int32
    vmax = max(1, 255 >> args.shift)
    gain = 255.0 / vmax  # яркость на экране относительно исходного максимума
    scale = args.scale or max(1, 512 // max(H, W))

    # ---- Проход 1: считаем число шагов до стабильности (без создания кадров)
    h = h0.clone()
    n = 0
    while True:
        nh = topple(h)
        if nh is None:
            break
        h = nh
        n += 1
    total = 3 * n
    print(f"Шагов до стабильности: {n} ({total} подшагов), песчинок осталось: {int(h.sum())}")

    stride = args.frame_every or max(1, math.ceil(total / max(1, args.max_frames)))

    # ---- Проход 2: собираем кадры
    frames = [to_frame(h0, gain, scale)]
    prev = h0
    for k in range(n):
        cur = topple(prev)
        for c in range(3):
            s = 3 * k + c + 1  # номер подшага
            if s % stride == 0 or s == total:
                mask = torch.tensor([i <= c for i in range(3)], device=dev).view(3, 1, 1)
                # каналы <= c уже обновлены в этом шаге, остальные ещё нет
                frames.append(to_frame(torch.where(mask, cur, prev), gain, scale))
        prev = cur

    durations = [args.duration] * len(frames)
    durations[-1] = args.hold
    frames[0].save(
        args.output, save_all=True, append_images=frames[1:],
        duration=durations, loop=0, optimize=False,
    )
    print(f"Готово: {args.output}, кадров: {len(frames)}, размер кадра {W*scale}x{H*scale}")


if __name__ == "__main__":
    sys.exit(main())