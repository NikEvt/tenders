import Link from "next/link";
import { Compass } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/empty-state";
import { ru } from "@/shared/i18n/ru";

export default function NotFound() {
  return (
    <EmptyState
      icon={<Compass strokeWidth={1.5} />}
      title={ru.errors.notFound}
      body={ru.errors.notFoundBody}
      action={
        <Button asChild variant="primary">
          <Link href="/tenders">{ru.catalog.title}</Link>
        </Button>
      }
    />
  );
}
