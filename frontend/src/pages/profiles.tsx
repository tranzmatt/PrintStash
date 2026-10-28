import { FilamentProfilesCard } from "@/components/filament-profiles-card";
import { PageContainer } from "@/components/ui/page-container";
import { PageHeader } from "@/components/ui/page-header";
import { useI18n } from "@/lib/i18n";
import { translateUiText } from "@/lib/locale";

export default function ProfilesPage() {
  const { locale } = useI18n();
  return (
    <PageContainer>
      <PageHeader
        title={translateUiText(locale, "Profiles")}
        description={translateUiText(locale, "profiles.description")}
      />
      <FilamentProfilesCard />
    </PageContainer>
  );
}
