import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { TabBar } from "@/components/ui/tabs";
import { ApiError, userMessage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { uiText } from "@/lib/locale";
import { slicerProfilesOptions } from "@/lib/queries/slicer-profiles";
import type { SlicerProfileRead, SlicerSettingsKind } from "@/types/slicer-profiles";

function SettingsTable({ profile }: { profile: SlicerProfileRead }) {
  const [kind, setKind] = useState<SlicerSettingsKind>("filament");
  const [search, setSearch] = useState("");
  const rows = Object.entries(profile.settings[kind]).filter(([key, value]) =>
    `${key} ${value}`.toLowerCase().includes(search.toLowerCase().trim()),
  );
  return (
    <div className="space-y-3 border-t bg-muted/20 p-4 sm:px-5">
      <TabBar
        tabs={[
          { key: "printer", label: uiText("profiles.printerSettings") },
          { key: "filament", label: uiText("profiles.filamentSettings") },
          { key: "process", label: uiText("profiles.processSettings") },
        ]}
        active={kind}
        onChange={setKind}
        showIndicator={false}
        className="flex-wrap gap-1 rounded-lg bg-background p-1 ring-1 ring-border"
        tabClassName="flex-1 whitespace-nowrap rounded-md px-3 py-2 text-xs font-medium text-muted-foreground transition-colors duration-press hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        activeTabClassName="bg-accent text-accent-foreground"
      />
      <Input
        aria-label={uiText("profiles.searchSettings")}
        placeholder={uiText("profiles.searchSettings")}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <p className="text-xs text-muted-foreground">{uiText("profiles.valuesHelp")}</p>
      {rows.length === 0 ? (
        <p className="py-3 text-sm text-muted-foreground">{uiText("profiles.noSettings")}</p>
      ) : (
        <dl className="divide-y divide-border">
          {rows.map(([key, value]) => (
            <div key={key} className="grid gap-1 py-2 text-sm sm:grid-cols-2 sm:gap-4">
              <dt className="min-w-0 break-words font-mono text-xs text-muted-foreground">{key}</dt>
              <dd className="min-w-0 whitespace-pre-wrap break-words">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

export function SlicerProfileDetails() {
  const { locale } = useI18n();
  const [cursors, setCursors] = useState<(number | null)[]>([null]);
  const beforeId = cursors[cursors.length - 1];
  const [expanded, setExpanded] = useState<number | null>(null);
  const query = useQuery(slicerProfilesOptions(beforeId));
  const denied = query.error instanceof ApiError && [401, 403, 404].includes(query.error.status);
  const data = denied ? undefined : query.data;

  return (
    <section aria-label={uiText("profiles.detected")}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-4 sm:px-5">
        <div className="flex min-w-0 gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
          </div>
          <div>
            <h2 className="text-sm font-semibold">{uiText("profiles.detected")}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{uiText("profiles.captureHelp")}</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="xs"
          onClick={() => void query.refetch()}
          loading={query.isFetching}
        >
          {uiText("Refresh")}
        </Button>
      </div>
      {query.isError && (
        <div role="alert" className="space-y-2 border-b p-4 text-sm text-destructive">
          <p>{userMessage(query.error)}</p>
          <Button variant="outline" onClick={() => void query.refetch()}>
            {uiText("Retry")}
          </Button>
        </div>
      )}
      {query.isPending ? (
        <div className="space-y-3 p-5">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : data ? (
        <>
          {data.items.length === 0 ? (
            <EmptyState
              icon={SlidersHorizontal}
              title={uiText("profiles.noCaptures")}
              description={uiText("profiles.noCapturesHelp")}
            />
          ) : (
            <div className="divide-y divide-border">
              {data.items.map((profile) => (
                <article key={profile.file_id}>
                  <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
                    <div className="min-w-0 space-y-1">
                      <h3 className="break-words text-sm font-medium">{profile.filename}</h3>
                      <p className="text-xs text-muted-foreground">
                        {profile.slicer_version ??
                          profile.slicer_name ??
                          uiText("profiles.slicerUnknown")}
                        {" · "}
                        {new Date(profile.uploaded_at).toLocaleString(locale)}
                      </p>
                      <p className="break-words text-xs text-muted-foreground">
                        {[
                          profile.settings.printer.printer_settings_id,
                          profile.settings.filament.filament_settings_id,
                          profile.settings.process.print_settings_id,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                      <Link
                        className="text-xs text-primary underline underline-offset-2"
                        to={`/models/${profile.model_id}`}
                      >
                        {uiText("profiles.sourceModel", { name: profile.model_name })}
                      </Link>
                    </div>
                    <Button
                      variant="outline"
                      size="xs"
                      aria-expanded={expanded === profile.file_id}
                      onClick={() =>
                        setExpanded(expanded === profile.file_id ? null : profile.file_id)
                      }
                    >
                      {expanded === profile.file_id
                        ? uiText("profiles.hideSettings")
                        : uiText("profiles.viewSettings")}
                    </Button>
                  </div>
                  {expanded === profile.file_id && <SettingsTable profile={profile} />}
                </article>
              ))}
            </div>
          )}
          <div className="flex justify-between gap-3 border-t p-3">
            <Button
              variant="outline"
              size="xs"
              disabled={cursors.length === 1}
              onClick={() => {
                setExpanded(null);
                setCursors(cursors.slice(0, -1));
              }}
            >
              {uiText("profiles.newer")}
            </Button>
            <Button
              variant="outline"
              size="xs"
              disabled={data.next_before_id === null}
              onClick={() => {
                if (data.next_before_id === null) return;
                setExpanded(null);
                setCursors([...cursors, data.next_before_id]);
              }}
            >
              {uiText("profiles.older")}
            </Button>
          </div>
        </>
      ) : null}
    </section>
  );
}
