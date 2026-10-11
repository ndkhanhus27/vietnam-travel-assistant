import {
  createContext,
  useContext,
  useEffect,
  type ReactNode,
} from "react";

export type Language = "vi";

const STORAGE_KEY = "vta_language";

type LocaleContextValue = {
  language: Language;
  t: (vi: string, en: string) => string;
};

const LocaleContext = createContext<LocaleContextValue>({
  language: "vi",
  t: (vi) => vi,
});

export function loadLanguage(
  _storage?: Pick<Storage, "getItem">,
): Language {
  return "vi";
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.lang = "vi";
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // The selected language still works for this session.
    }
  }, []);

  return <LocaleContext.Provider value={vietnameseLocale}>{children}</LocaleContext.Provider>;
}

const vietnameseLocale: LocaleContextValue = { language: "vi", t: (vi) => vi };

export function useLocale() {
  return useContext(LocaleContext);
}
