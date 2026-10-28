"use client";

import { useEffect, useState } from "react";

import { Check, Folder, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Localized } from "@/components/ui/localized";
import { useUiLocale } from "@/lib/i18n";
import { uiText } from "@/lib/locale";
import { useCollectionSearch } from "@/lib/queries";
import type { CollectionNodeRead, CollectionRole } from "@/types";

export interface CollectionPickerProps {
  /** Offer only collections the reader holds at least this role on. */
  minRole: CollectionRole;
  /** Focus the search when this picker opens inside a popover. */
  autoFocus?: boolean;
  /** The chosen collection's path; `""` when the "none" option is chosen; null for nothing yet. */
  selectedPath: string | null;
  /** Called with the chosen collection, or null for the "none" option. */
  onSelect: (collection: CollectionNodeRead | null) => void;
  /** Label of an extra first option meaning "no collection"; omitted when there is none. */
  noneLabel?: string;
  /** Collections that may not be chosen, e.g. a folder being moved and its subtree. */
  excludePaths?: string[];
  /** What to say when nothing matches. */
  emptyLabel: string;
}

/**
 * Pick a destination collection by searching for it.
 *
 * Pickers used to list every collection the reader could see, which on a large
 * library meant loading the whole tree to open a dialog (#295). This asks the
 * server for a page of matches instead, each labelled with its full name path.
 */
export function CollectionPicker({
  minRole,
  autoFocus = false,
  selectedPath,
  onSelect,
  noneLabel,
  excludePaths = [],
  emptyLabel,
}: CollectionPickerProps) {
  useUiLocale();
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearched(query.trim()), 200);
    return () => clearTimeout(timer);
  }, [query]);
  const results = useCollectionSearch(searched, minRole);
  const options = (
    results.isError ? [] : (results.data?.pages.flatMap((page) => page.items) ?? [])
  ).filter(
    (collection) =>
      !excludePaths.some(
        (path) => collection.path === path || collection.path.startsWith(`${path}/`),
      ),
  );

  return (
    <Localized>
      <div>
        <div className="relative mb-2">
          <Search
            className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground"
            aria-hidden
          />
          <Input
            autoFocus={autoFocus}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={uiText("Find destination...")}
            aria-label={uiText("Find destination")}
            className="pl-9"
          />
        </div>
        <div
          role="listbox"
          aria-label={uiText("Collections")}
          className="max-h-72 overflow-x-hidden overflow-y-auto rounded-md border border-border"
        >
          {noneLabel !== undefined && (
            <button
              type="button"
              role="option"
              aria-selected={selectedPath === ""}
              onClick={() => onSelect(null)}
              className={`flex w-full min-w-0 items-start gap-3 px-3 py-2.5 text-left text-sm transition-colors duration-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${
                selectedPath === ""
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-muted"
              }`}
            >
              <Folder className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 break-words">{noneLabel}</span>
              {selectedPath === "" && <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />}
            </button>
          )}
          {options.map((collection) => (
            <button
              key={collection.id}
              type="button"
              role="option"
              aria-selected={selectedPath === collection.path}
              aria-label={`${collection.display_path} (${collection.model_count})`}
              onClick={() => onSelect(collection)}
              className={`flex w-full min-w-0 items-start gap-3 px-3 py-2.5 text-left text-sm transition-colors duration-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${
                selectedPath === collection.path
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-muted"
              }`}
            >
              <Folder className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 space-y-0.5">
                <span className="block break-words font-medium">{collection.name}</span>
                {collection.display_path !== collection.name && (
                  <span className="block break-words text-xs text-muted-foreground">
                    {collection.display_path}
                  </span>
                )}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                ({collection.model_count})
              </span>
              {selectedPath === collection.path && (
                <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              )}
            </button>
          ))}
          {results.isPending && (
            <p role="status" className="px-3 py-4 text-sm text-muted-foreground">
              {uiText("Loading...")}
            </p>
          )}
          {results.isSuccess && results.hasNextPage && (
            <button
              type="button"
              disabled={results.isFetchingNextPage}
              onClick={() => void results.fetchNextPage()}
              className="w-full px-3 py-2 text-left font-mono text-3xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {uiText("Show more folders")}
            </button>
          )}
          {results.isError && (
            <div role="alert" className="space-y-2 px-3 py-4 text-sm text-muted-foreground">
              <p>{uiText("Folders could not be loaded.")}</p>
              <Button
                type="button"
                variant="outline"
                size="xs"
                onClick={() => void results.refetch()}
              >
                {uiText("Retry")}
              </Button>
            </div>
          )}
          {results.isSuccess && options.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">{emptyLabel}</p>
          )}
        </div>
      </div>
    </Localized>
  );
}
