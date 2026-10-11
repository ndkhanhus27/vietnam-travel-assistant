import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ConfigProvider, theme as antdTheme } from "antd";

export type Appearance = "pink" | "yellow" | "green";
export type ThemeMode = "light" | "dark" | "system";

export const appearanceOptions: Array<{
  value: Appearance;
  label: string;
  swatch: string;
}> = [
  { value: "pink", label: "Hồng san hô", swatch: "#fff0ed" },
  { value: "yellow", label: "Vàng", swatch: "#fff7cc" },
  { value: "green", label: "Xanh lá", swatch: "#eef8d8" },
];

const STORAGE_KEY = "vta_appearance";
const MODE_STORAGE_KEY = "vta_theme_mode";

type AppearanceContextValue = {
  appearance: Appearance;
  setAppearance: (appearance: Appearance) => void;
  mode: ThemeMode;
  resolvedMode: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
};

const AppearanceContext = createContext<AppearanceContextValue>({
  appearance: "pink",
  setAppearance: () => undefined,
  mode: "light",
  resolvedMode: "light",
  setMode: () => undefined,
});

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

export function loadThemeMode(
  storage: Pick<Storage, "getItem"> = localStorage,
): ThemeMode {
  try {
    const value = storage.getItem(MODE_STORAGE_KEY);
    return value === "dark" || value === "system" ? value : "light";
  } catch {
    return "light";
  }
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearanceState] = useState<Appearance>(loadAppearance);
  const [mode, setModeState] = useState<ThemeMode>(loadThemeMode);
  const [systemDark, setSystemDark] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  const resolvedMode = mode === "system" ? (systemDark ? "dark" : "light") : mode;

  useEffect(() => {
    document.documentElement.dataset.appearance = appearance;
    saveAppearance(appearance);
  }, [appearance]);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedMode;
    try {
      localStorage.setItem(MODE_STORAGE_KEY, mode);
    } catch {
      // The selected mode still works for this session.
    }
  }, [mode, resolvedMode]);

  const value = useMemo(
    () => ({
      appearance,
      setAppearance: setAppearanceState,
      mode,
      resolvedMode,
      setMode: setModeState,
    }),
    [appearance, mode, resolvedMode],
  );
  const primaryColor = appearance === "green"
    ? "#3f8f68"
    : appearance === "yellow" ? "#aa7a16" : "#5d63ff";
  return (
    <AppearanceContext.Provider value={value}>
      <ConfigProvider
        theme={{
          algorithm: resolvedMode === "dark"
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: primaryColor,
            borderRadius: 8,
            fontFamily: 'Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
            controlHeight: 40,
          },
        }}
      >
        {children}
      </ConfigProvider>
    </AppearanceContext.Provider>
  );
}

export function useAppearance() {
  return useContext(AppearanceContext);
}
