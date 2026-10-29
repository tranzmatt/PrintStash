import { useState } from "react";
import { LibraryFilterMenu } from "@/components/library-filter-menu";
import { LibraryFilterChoice } from "@/components/library-filter-choice";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/lib/i18n";
import { FILTER_INPUT } from "@/lib/filter-input";
import type { PrinterRead, TagRead } from "@/types";

/** Tags and printer location share ModelGrid's existing URL-owned filter state. */
export function LibraryBaseFilters({
  tags,
  printers,
  selectedTags,
  selectedPrinterId,
  selectedPrinterPresence,
  onTagsChange,
  onPrinterChange,
  onPrinterPresenceChange,
  canViewPrinters,
}: {
  tags: TagRead[];
  printers: PrinterRead[];
  selectedTags: string[];
  selectedPrinterId: number | null;
  selectedPrinterPresence: "any" | "none" | null;
  onTagsChange: (tags: string[]) => void;
  onPrinterChange: (id: number | null) => void;
  onPrinterPresenceChange: (presence: "any" | "none" | null) => void;
  canViewPrinters: boolean;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const visibleTags = tags.filter((tag) => tag.name.toLowerCase().includes(query.toLowerCase()));
  return (
    <>
      {canViewPrinters && (
        <LibraryFilterMenu
          label={t("Printer")}
          count={Number(selectedPrinterId !== null || selectedPrinterPresence !== null)}
        >
          <LibraryFilterChoice
            label={t("Any location")}
            checked={selectedPrinterId === null && selectedPrinterPresence === null}
            onChange={() => onPrinterChange(null)}
          />
          <LibraryFilterChoice
            label={t("On a printer")}
            checked={selectedPrinterPresence === "any"}
            onChange={(checked) => onPrinterPresenceChange(checked ? "any" : null)}
          />
          <LibraryFilterChoice
            label={t("Vault only")}
            checked={selectedPrinterPresence === "none"}
            onChange={(checked) => onPrinterPresenceChange(checked ? "none" : null)}
          />
          {printers.map((printer) => (
            <LibraryFilterChoice
              key={printer.id}
              label={printer.name}
              checked={selectedPrinterId === printer.id}
              onChange={(checked) => onPrinterChange(checked ? printer.id : null)}
            />
          ))}
        </LibraryFilterMenu>
      )}
      {(tags.length > 0 || selectedTags.length > 0) && (
        <LibraryFilterMenu label={t("Tags")} count={selectedTags.length}>
          <Input
            aria-label={t("Filter tags...")}
            placeholder={t("Filter tags...")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className={FILTER_INPUT}
          />
          <div className="mt-2">
            {visibleTags.map((tag) => (
              <LibraryFilterChoice
                key={tag.id}
                label={tag.name}
                count={tag.model_count + (tag.multipart_model_count ?? 0)}
                checked={selectedTags.includes(tag.slug)}
                onChange={(checked) =>
                  onTagsChange(
                    checked
                      ? [...selectedTags, tag.slug]
                      : selectedTags.filter((slug) => slug !== tag.slug),
                  )
                }
              />
            ))}
            {visibleTags.length === 0 && (
              <p className="px-2 py-1 text-xs text-muted-foreground">{t("No matching tags.")}</p>
            )}
          </div>
        </LibraryFilterMenu>
      )}
    </>
  );
}
