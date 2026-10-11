import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Language = "vi" | "en";

const STORAGE_KEY = "vta_language";

type LocaleContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (vi: string, en: string) => string;
};

const LocaleContext = createContext<LocaleContextValue>({
  language: "vi",
  setLanguage: () => undefined,
  t: (vi) => vi,
});

export function loadLanguage(
  storage: Pick<Storage, "getItem"> = localStorage,
): Language {
  try {
    return storage.getItem(STORAGE_KEY) === "en" ? "en" : "vi";
  } catch {
    return "vi";
  }
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(loadLanguage);

  useEffect(() => {
    document.documentElement.lang = language;
    try {
      localStorage.setItem(STORAGE_KEY, language);
    } catch {
      // The selected language still works for this session.
    }
  }, [language]);

  const value = useMemo<LocaleContextValue>(() => ({
    language,
    setLanguage,
    t: (vi, en) => language === "vi" ? vi : en,
  }), [language]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  return useContext(LocaleContext);
}
