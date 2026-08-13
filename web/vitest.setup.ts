import "@testing-library/jest-dom/vitest";

/**
 * В jsdom нет canvas, и `getContext` печатает «Not implemented» в stderr на
 * каждую отрисовку шкалы сроков. Возвращаем null явно: измеритель
 * (`shared/ui/chart/measure.ts`) на этот случай уходит на детерминированную
 * подменную ширину — ровно то поведение, которое нужно тестам и серверному
 * рендеру, только без шума в выводе.
 */
HTMLCanvasElement.prototype.getContext = (() => null) as HTMLCanvasElement["getContext"];
