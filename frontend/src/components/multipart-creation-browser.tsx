/** A bounded library browser for choosing the first pieces of a multipart set. */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Box } from "lucide-react";
import { useCollectionChildren, useCollectionLookup, useQueryApi } from "@/lib/queries";
import { useI18n } from "@/lib/i18n";
import { uiText } from "@/lib/locale";
import { getSessionVersion } from "@/lib/session-transport";
import { Button } from "@/components/ui/button";
import {
  SelectionBrowserToolbar,
  SelectionBrowserBreadcrumbs,
  SelectionFolderCard,
  SelectionItemCard,
} from "@/components/selection-browser";
import type { CollectionNodeRead, ModelListItem } from "@/types";

const MULTIPART_INITIAL_LIMIT = 100;
const PAGE_SIZE = 24;

export function MultipartCreationBrowser({
  selected,
  onSelectionChange,
  initialCollection,
  disabled,
}: {
  selected: Map<number, ModelListItem>;
  onSelectionChange: (models: Map<number, ModelListItem>) => void;
  initialCollection: CollectionNodeRead | null;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const api = useQueryApi();
  const [collection, setCollection] = useState(initialCollection);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<Array<string | null>>([]);
  useEffect(() => {
    if (query.trim() === search) return;
    const timer = setTimeout(() => {
      setSearch(query.trim());
      setCursor(null);
      setPrevious([]);
    }, 200);
    return () => clearTimeout(timer);
  }, [query, search]);
  const children = useCollectionChildren(collection?.id ?? null, { enabled: !search });
  const lookup = useCollectionLookup(collection?.path ?? null);
  const models = useQuery({
    queryKey: [
      "models",
      "multipart-creation",
      getSessionVersion(),
      search,
      collection?.path ?? null,
      cursor,
    ],
    queryFn: ({ signal }) =>
      api.listModelPage(
        {
          q: search || undefined,
          collection: search ? undefined : collection?.path,
          direct: !search,
          limit: PAGE_SIZE,
          sort: "name-asc",
          cursor: cursor ?? undefined,
        },
        { signal },
      ),
  });
  const folders = children.isError
    ? []
    : (children.data?.pages.flatMap((page) => page.items) ?? []);
  const items = models.isError ? [] : (models.data?.items ?? []);
  const ancestors = lookup.data
    ? [...lookup.data.ancestors, lookup.data.collection]
    : collection
      ? [collection]
      : [];
  function navigate(next: CollectionNodeRead | null) {
    setCollection(next);
    setQuery("");
    setSearch("");
    setCursor(null);
    setPrevious([]);
  }
  function toggle(model: ModelListItem) {
    const next = new Map(selected);
    if (next.has(model.id)) next.delete(model.id);
    else if (next.size < MULTIPART_INITIAL_LIMIT) next.set(model.id, model);
    onSelectionChange(next);
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <SelectionBrowserToolbar
        query={query}
        onQueryChange={setQuery}
        searchLabel={t("multipart.searchModels")}
        summary={t("multipart.creationSelectionHelp", {
          count: String(selected.size),
          limit: String(MULTIPART_INITIAL_LIMIT),
        })}
        selectLabel={t("multipart.selectPage")}
        clearLabel={uiText("Clear selection")}
        selectDisabled={
          disabled ||
          models.isFetching ||
          !items.length ||
          items.every((item) => selected.has(item.id)) ||
          selected.size + items.filter((item) => !selected.has(item.id)).length >
            MULTIPART_INITIAL_LIMIT
        }
        clearDisabled={disabled || selected.size === 0}
        onSelectAll={() =>
          onSelectionChange(
            new Map([...selected, ...items.map((item) => [item.id, item] as const)]),
          )
        }
        onClear={() => onSelectionChange(new Map())}
      />
      <SelectionBrowserBreadcrumbs
        label={t("multipart.browseCollections")}
        items={[
          {
            key: "root",
            label: t("multipart.allModels"),
            current: !collection,
            onClick: () => navigate(null),
          },
          ...ancestors.map((item) => ({
            key: String(item.id),
            label: item.name,
            current: item.id === collection?.id,
            onClick: () => navigate(item),
          })),
        ]}
      />
      <div className="min-h-40 min-w-0 overflow-y-auto overscroll-contain pr-1">
        {!search && children.isError && (
          <div role="alert" className="flex flex-wrap items-center gap-2 py-3 text-sm">
            {t("multipart.collectionsError")}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void children.refetch()}
            >
              {t("multipart.retry")}
            </Button>
          </div>
        )}
        {models.isError && (
          <div role="alert" className="flex flex-wrap items-center gap-2 py-3 text-sm">
            {t("multipart.candidatesError")}
            <Button type="button" variant="outline" size="sm" onClick={() => void models.refetch()}>
              {t("multipart.retry")}
            </Button>
          </div>
        )}
        {models.isPending && (
          <p role="status" className="py-5 text-sm text-muted-foreground">
            {t("multipart.loadingModels")}
          </p>
        )}
        <ul
          aria-label={t("multipart.modelPicker")}
          className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3"
        >
          {!search &&
            folders.map((folder) => (
              <li key={`folder/${folder.id}`} className="min-w-0">
                <SelectionFolderCard
                  name={folder.name}
                  path={folder.display_path}
                  openLabel={uiText("Open folder {value1}", { value1: folder.name })}
                  onOpen={() => navigate(folder)}
                  summary={t(folder.model_count === 1 ? "multipart.model" : "multipart.models", {
                    count: String(folder.model_count),
                  })}
                />
              </li>
            ))}
          {items.map((item) => (
            <li key={item.id} className="min-w-0">
              <SelectionItemCard
                name={item.name}
                label={item.name}
                title={item.name}
                icon={<Box className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />}
                summary={item.collection_label ?? t("multipart.vaultOnly")}
                selected={selected.has(item.id)}
                disabled={
                  disabled || (!selected.has(item.id) && selected.size >= MULTIPART_INITIAL_LIMIT)
                }
                onToggle={() => toggle(item)}
              />
            </li>
          ))}
        </ul>
        {!search && children.hasNextPage && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            loading={children.isFetchingNextPage}
            onClick={() => void children.fetchNextPage()}
          >
            {uiText("Show more folders")}
          </Button>
        )}
        {models.isSuccess &&
          !items.length &&
          (search || (!children.isPending && !children.isError && !folders.length)) && (
            <p className="py-5 text-sm text-muted-foreground">{t("multipart.noCandidates")}</p>
          )}
      </div>
      {(previous.length > 0 || models.data?.next_cursor) && (
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={models.isFetching || !previous.length}
            onClick={() => {
              setCursor(previous.at(-1) ?? null);
              setPrevious(previous.slice(0, -1));
            }}
          >
            {t("multipart.previousPage")}
          </Button>
          <span className="text-sm tabular-nums">
            {t("multipart.pageNumber", { number: String(previous.length + 1) })}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={models.isFetching || !models.data?.next_cursor}
            onClick={() => {
              setPrevious([...previous, cursor]);
              setCursor(models.data?.next_cursor ?? null);
            }}
          >
            {t("multipart.nextPage")}
          </Button>
        </div>
      )}
    </div>
  );
}
