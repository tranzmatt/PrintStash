import { useQueryClient } from "@tanstack/react-query";
import { refreshLibraryMetadata } from "@/features/library/metadata";
import { getSessionVersion, requireSessionVersion } from "@/lib/session-transport";
import { ChevronDown, Folder } from "lucide-react";
import { useState } from "react";
import { uiText } from "@/lib/locale";
import { useI18n, useUiLocale } from "@/lib/i18n";
import { useRouter } from "@/lib/navigation";
import { createMultipartModel } from "@/lib/api";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import type { CollectionNodeRead } from "@/types";
import { CollectionPicker } from "@/components/collection-picker";
import { multipartError, detailHref } from "@/lib/multipart-model-presentation";

/** The folder a new set starts in: its id is what is saved, its path what is shown chosen. */
export type CollectionChoice = Pick<CollectionNodeRead, "id" | "path" | "name" | "display_path">;

export function NewMultipartModelModal({
  open,
  onClose,
  collection,
  returnTo,
}: {
  open: boolean;
  onClose: () => void;
  collection: CollectionChoice | null;
  returnTo?: string;
}) {
  useUiLocale();
  const { t } = useI18n();
  const router = useRouter();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [target, setTarget] = useState<CollectionChoice | null>(collection);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function closeModal() {
    setName("");
    setDescription("");
    setTarget(collection);
    setPickerOpen(false);
    setError(null);
    onClose();
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    const session = getSessionVersion();
    setBusy(true);
    setError(null);
    try {
      const created = await createMultipartModel({
        name: name.trim(),
        description: description.trim() || null,
        collection_id: target?.id ?? null,
      });
      requireSessionVersion(session);
      refreshLibraryMetadata(client, session);
      closeModal();
      router.push(detailHref(created.id, returnTo));
    } catch (cause) {
      setError(multipartError(cause, t, "multipart.createError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={busy ? () => undefined : closeModal}
      title={t("multipart.new")}
      className="max-w-xl"
    >
      <form onSubmit={submit} className="space-y-5">
        <p className="text-sm text-muted-foreground">{t("multipart.linkedNotice")}</p>
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">{t("multipart.name")}</span>
          <Input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("multipart.namePlaceholder")}
            maxLength={200}
            required
          />
        </label>
        <div className="space-y-1.5">
          <span className="text-sm font-medium">{t("multipart.collectionLabel")}</span>
          <DropdownMenu
            open={pickerOpen}
            onOpenChange={setPickerOpen}
            align="start"
            role="dialog"
            aria-label={t("multipart.collectionLabel")}
            portal
            className="w-full"
            contentClassName="w-96 max-w-[calc(100vw-3rem)] rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-lg"
            trigger={
              <Button
                type="button"
                variant="outline"
                className="w-full justify-start font-normal"
                aria-label={t("multipart.collectionLabel")}
                data-menu-trigger
                aria-haspopup="dialog"
                aria-expanded={pickerOpen}
                title={target?.display_path ?? t("multipart.vaultOnly")}
                disabled={busy}
                onClick={() => setPickerOpen((value) => !value)}
              >
                <Folder className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-left">
                  {target?.name ?? t("multipart.vaultOnly")}
                </span>
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              </Button>
            }
          >
            <CollectionPicker
              autoFocus
              minRole="edit"
              selectedPath={target?.path ?? ""}
              onSelect={(picked) => {
                setTarget(picked);
                setPickerOpen(false);
              }}
              noneLabel={t("multipart.vaultOnly")}
              emptyLabel={uiText("No editable collections.")}
            />
          </DropdownMenu>
          {target && target.display_path !== target.name && (
            <p className="break-words text-xs text-muted-foreground">{target.display_path}</p>
          )}
        </div>
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">{t("multipart.descriptionLabel")}</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("multipart.descriptionPlaceholder")}
            rows={3}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={closeModal} disabled={busy}>
            {t("multipart.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!name.trim()}>
            {t("multipart.create")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
