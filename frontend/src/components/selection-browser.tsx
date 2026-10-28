/** Shared ZIP/library selection UI; callers own browsing, permissions and pagination. */
import type { ReactNode } from "react";
import { CheckSquare, ChevronRight, Folder, Search, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export function SelectionBrowserToolbar({
  query,
  onQueryChange,
  searchLabel,
  summary,
  selectLabel,
  clearLabel,
  onSelectAll,
  onClear,
  selectDisabled,
  clearDisabled,
}: {
  query: string;
  onQueryChange: (query: string) => void;
  searchLabel: string;
  summary: ReactNode;
  selectLabel: string;
  clearLabel: string;
  onSelectAll: () => void;
  onClear: () => void;
  selectDisabled: boolean;
  clearDisabled: boolean;
}) {
  return (
    <>
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <Input
          autoFocus
          aria-label={searchLabel}
          placeholder={searchLabel}
          value={query}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.preventDefault();
          }}
          maxLength={128}
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-border bg-muted/30 px-3 py-2">
        <p className="text-xs text-muted-foreground">{summary}</p>
        <div className="flex flex-wrap items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={selectDisabled}
            onClick={onSelectAll}
          >
            {selectLabel}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={clearDisabled}
            onClick={onClear}
          >
            {clearLabel}
          </Button>
        </div>
      </div>
    </>
  );
}

export function SelectionBrowserBreadcrumbs({
  label,
  items,
}: {
  label: string;
  items: Array<{ key: string; label: string; current: boolean; onClick: () => void }>;
}) {
  return (
    <nav aria-label={label} className="flex flex-wrap items-center gap-1 text-sm">
      {items.map((item, index) => (
        <span key={item.key} className="flex min-w-0 items-center gap-1">
          {index > 0 && (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto whitespace-normal break-words text-left"
            onClick={item.onClick}
            aria-current={item.current ? "page" : undefined}
          >
            {item.label}
          </Button>
        </span>
      ))}
    </nav>
  );
}

export function SelectionFolderCard({
  name,
  path,
  openLabel,
  onOpen,
  summary,
  selection,
}: {
  name: string;
  path: string;
  openLabel: string;
  onOpen: () => void;
  summary: ReactNode;
  selection?: { selected: boolean; partial: boolean; label: string; onToggle: () => void };
}) {
  return (
    <div
      className={cn(
        "flex h-28 flex-col justify-between gap-2 rounded-lg border p-3",
        selection?.selected
          ? "border-primary bg-accent text-accent-foreground"
          : selection?.partial
            ? "border-border bg-accent/50 text-accent-foreground"
            : "border-border bg-card text-card-foreground",
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        <Button
          type="button"
          variant="ghost"
          className="h-auto min-w-0 flex-1 justify-start gap-2 whitespace-normal p-0 text-left hover:bg-transparent"
          aria-label={openLabel}
          title={path}
          onClick={onOpen}
        >
          <Folder className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="line-clamp-2 break-words text-sm font-medium">{name}</span>
        </Button>
        {selection && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            aria-pressed={selection.selected}
            aria-label={selection.label}
            onClick={selection.onToggle}
          >
            {selection.selected ? (
              <CheckSquare className="h-5 w-5" aria-hidden />
            ) : (
              <Square className="h-5 w-5" aria-hidden />
            )}
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{summary}</p>
    </div>
  );
}

export function SelectionItemCard({
  name,
  label,
  title,
  icon,
  summary,
  selected,
  disabled,
  onToggle,
}: {
  name: string;
  label: string;
  title: string;
  icon: ReactNode;
  summary: ReactNode;
  selected: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "flex h-28 w-full flex-col justify-between gap-2 rounded-lg border p-3 text-left transition-transform duration-press active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        selected
          ? "border-primary bg-accent text-accent-foreground"
          : "border-border bg-card text-card-foreground hover:bg-muted",
      )}
    >
      <span className="flex w-full items-start justify-between gap-2">
        {icon}
        {selected ? (
          <CheckSquare className="h-5 w-5 shrink-0" aria-hidden />
        ) : (
          <Square className="h-5 w-5 shrink-0" aria-hidden />
        )}
      </span>
      <span className="line-clamp-2 break-words text-sm font-medium" title={title}>
        {name}
      </span>
      <span className="truncate text-xs text-muted-foreground">{summary}</span>
    </button>
  );
}
