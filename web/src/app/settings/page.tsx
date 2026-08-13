import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { ru } from "@/shared/i18n/ru";
import { SettingsView } from "@/widgets/settings-view/ui/settings-view";

export const metadata: Metadata = { title: ru.settings.title };

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.settings.title} meta={ru.settings.configNote} />
      <SettingsView />
    </div>
  );
}
