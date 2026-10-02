import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Appearance = "pink" | "yellow" | "green";

export const appearanceOptions: Array<{
  value: Appearance;
  label: string;
  swatch: string;
}> = [
  { value: "pink", label: "Hồng", swatch: "#fff0ed" },
  { value: "yellow", label: "Vàng", swatch: "#fff7cc" },
  { value: "green", label: "Xanh lá", swatch: "#eef8d8" },
];

const STORAGE_KEY = "vta_appearance";

type AppearanceContextValue = {
  appearance: Appearance;
  setAppearance: (appearance: Appearance) => void;
};

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export function loadAppearance(
  storage: Pick<Storage, "getItem"> = localStorage,
): Appearance {
  try {
    const value = storage.getItem(STORAGE_KEY);
    return value === "yellow" || value === "green" ? value : "pink";
  } catch {
    return "pink";
  }
}

export function saveAppearance(
  appearance: Appearance,
  storage: Pick<Storage, "setItem"> = localStorage,
) {
  try {
    storage.setItem(STORAGE_KEY, appearance);
  } catch {
    // Keep the in-memory selection when browser storage is unavailable.
  }
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearanceState] = useState<Appearance>(loadAppearance);

  useEffect(() => {
    document.documentElement.dataset.appearance = appearance;
    saveAppearance(appearance);
  }, [appearance]);

  const value = useMemo(
    () => ({ appearance, setAppearance: setAppearanceState }),
    [appearance],
  );
  return (
    <AppearanceContext.Provider value={value}>
      {children}
    </AppearanceContext.Provider>
  );
}

export function useAppearance() {
  const value = useContext(AppearanceContext);
  if (!value) {
    throw new Error("useAppearance must be used inside AppearanceProvider");
  }
  return value;
}
