"use client";

import { uiText } from "@/lib/locale";
import { useUiLocale } from "@/lib/i18n";

import { LayoutGrid } from "lucide-react";
import { ProtectedThumbnail } from "@/components/protected-thumbnail";
import { Localized } from "@/components/ui/localized";
import { cn } from "@/lib/utils";
import type { FilePlate } from "@/types";
import { plateLabel } from "./presentation";

const chip =
  "flex h-14 shrink-0 items-center gap-2 rounded border px-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * Choose which plate of a multi-plate 3MF the viewer shows, or all of them.
 * ``selected`` is the shown plate's number; ``null`` shows the whole build.
 */
export function PlatePicker({
  plates,
  selected,
  onSelect,
}: {
  plates: FilePlate[];
  selected: number | null;
  onSelect: (plate: number | null) => void;
}) {
  useUiLocale();
  const state = (active: boolean) =>
    active
      ? "border-primary bg-accent text-accent-foreground"
      : "border-outline-variant bg-surface-container-lowest text-on-surface-variant hover:bg-surface-container-high";
  return (
    <Localized>
      <div
        role="group"
        aria-label={uiText("Plates")}
        className="flex w-full min-w-0 gap-1.5 overflow-x-auto border-t border-outline-variant bg-surface-container-low p-2"
      >
        <button
          type="button"
          aria-pressed={selected === null}
          onClick={() => onSelect(null)}
          className={cn(chip, state(selected === null))}
        >
          <LayoutGrid className="h-4 w-4" aria-hidden />
          <span className="font-mono text-2xs uppercase tracking-wider">
            {uiText("All plates")}
          </span>
        </button>
        {plates.map((plate) => (
          <button
            key={plate.number}
            type="button"
            aria-pressed={selected === plate.number}
            disabled={plate.object_count === 0}
            onClick={() => onSelect(plate.number)}
            title={plate.name ?? uiText("Plate {value1}", { value1: plateLabel(plate) })}
            className={cn(
              chip,
              "max-w-60 disabled:cursor-disabled disabled:opacity-50",
              state(selected === plate.number),
            )}
          >
            <ProtectedThumbnail
              path={plate.image_url}
              alt=""
              className="h-10 w-10 shrink-0 overflow-hidden rounded-sm bg-surface-container"
              imageClassName="h-full w-full object-contain"
              placeholder={null}
            />
            <span className="min-w-0">
              <span className="block font-mono text-2xs uppercase tracking-wider">
                {uiText("Plate {value1}", { value1: plateLabel(plate) })}
              </span>
              {plate.name && (
                <span className="block truncate text-xs text-on-surface">{plate.name}</span>
              )}
              <span className="block text-3xs text-on-surface-variant">
                {uiText("Objects: {value1}", { value1: String(plate.object_count) })}
              </span>
            </span>
          </button>
        ))}
      </div>
    </Localized>
  );
}
