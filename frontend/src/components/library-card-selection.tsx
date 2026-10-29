import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

/** Paired with group/selection-card on the Model or folder card. */
export function LibraryCardSelection({
  selecting,
  checked,
  label,
  onChange,
}: {
  selecting: boolean;
  checked: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <div
      className={cn(
        "absolute left-2 top-2 z-10 rounded bg-card/90 p-1.5 shadow-sm transition-opacity duration-fast",
        !selecting &&
          !checked &&
          "[@media(hover:hover)_and_(pointer:fine)]:opacity-0 [@media(hover:hover)_and_(pointer:fine)]:pointer-events-none group-hover/selection-card:opacity-100 group-hover/selection-card:pointer-events-auto group-focus-within/selection-card:opacity-100 group-focus-within/selection-card:pointer-events-auto",
      )}
    >
      <Checkbox checked={checked} onChange={onChange} ariaLabel={label} />
    </div>
  );
}
