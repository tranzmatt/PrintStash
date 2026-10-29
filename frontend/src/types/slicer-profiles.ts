export type ProfileSettingsKind = "printer" | "filament";

export type SlicerSettingsKind = "printer" | "filament" | "process";

export interface SlicerProfileRead {
  file_id: number;
  model_id: number;
  model_name: string;
  filename: string;
  uploaded_at: string;
  printer_model: string | null;
  slicer_name: string | null;
  slicer_version: string | null;
  settings: Record<SlicerSettingsKind, Record<string, string>>;
}

export interface SlicerProfilePage {
  items: SlicerProfileRead[];
  next_before_id: number | null;
}
