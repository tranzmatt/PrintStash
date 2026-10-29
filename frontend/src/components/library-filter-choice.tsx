import { Checkbox } from "@/components/ui/checkbox";

/** Every facet uses the same checkbox, spacing and count treatment. */
export function LibraryFilterChoice({
  label,
  count,
  checked,
  onChange,
}: {
  label: string;
  count?: number | null;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-action items-center gap-2 rounded px-2 py-1.5 text-xs transition-colors duration-press hover:bg-muted">
      <Checkbox
        className="h-4 w-4 shrink-0"
        ariaLabel={label}
        checked={checked}
        onChange={onChange}
      />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count != null && (
        <span className="min-w-[18px] rounded bg-muted px-1 py-0.5 text-center text-2xs font-medium text-muted-foreground">
          {count}
        </span>
      )}
    </label>
  );
}
