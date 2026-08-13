import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { ru } from "@/shared/i18n/ru";
import { ProfileView } from "@/widgets/profile-view/ui/profile-view";

export const metadata: Metadata = { title: ru.profile.title };

export default function ProfilePage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.profile.title} />
      <ProfileView />
    </div>
  );
}
