import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UiLang } from "@/lib/i18n";

export type Theme = "system" | "light" | "dark";
export type Sheet = null | "menu" | "citations" | "install" | "mic" | "about" | "trust" | "kyc" | "documents" | "claim" | "loan";
/** The trust badges a reply can carry (see Verification in @sahaj/contracts). */
export type TrustLevel = "verified" | "engine" | "checked";

interface UiState {
  lang: UiLang;
  theme: Theme;
  /** The person has seen the mic explainer (shown once, before the browser's permission prompt). */
  micExplained: boolean;
  installDismissed: boolean;
  /** The sheet on top. */
  sheet: Sheet;
  /** Sheets still open underneath it (the menu, when Install or About was opened from it), bottom first. */
  sheetStack: Exclude<Sheet, null>[];
  /** Citations sheet: the assistant message and the citation to highlight. */
  citation: { itemId: string; citationId: string } | null;
  /** Trust sheet: the badge that was tapped, shown highlighted. */
  trustLevel: TrustLevel | null;
  /** Desktop side panel: which card is open (null = latest). */
  panelItemId: string | null;
  panelOpen: boolean;
  confirmWithdraw: null | import("@sahaj/contracts").ConsentPurpose;
  /** Android/desktop Chrome: the inline "Add Sahaj to your home screen" card in the conversation. */
  installCard: boolean;
}

const browserLang: UiLang = typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("hi") ? "hi" : "en";

export const useUi = create<UiState>()(
  persist(
    (): UiState => ({
      lang: browserLang,
      theme: "system",
      micExplained: false,
      installDismissed: false,
      sheet: null,
      sheetStack: [],
      citation: null,
      trustLevel: null,
      panelItemId: null,
      panelOpen: true,
      confirmWithdraw: null,
      installCard: false,
    }),
    {
      name: "sahaj-ui",
      // only preferences survive a reload; open sheets don't
      partialize: (s) => ({ lang: s.lang, theme: s.theme, micExplained: s.micExplained, installDismissed: s.installDismissed }),
    },
  ),
);

/**
 * Opens a sheet on top of the one showing (which stays open underneath), with any state it reads. The content a
 * sheet shows (a citation, a trust level) is left in place when it closes, so it doesn't empty while sliding away.
 */
export const openSheet = (sheet: Exclude<Sheet, null>, extra: Partial<UiState> = {}) =>
  useUi.setState((s) => ({
    ...extra,
    sheet,
    sheetStack: s.sheet && s.sheet !== sheet ? [...s.sheetStack.filter((x) => x !== sheet), s.sheet] : s.sheetStack.filter((x) => x !== sheet),
  }));

/** Closes the top sheet: the one underneath (if any) is showing again. */
export const closeSheet = () =>
  useUi.setState((s) => ({ sheet: s.sheetStack.at(-1) ?? null, sheetStack: s.sheetStack.slice(0, -1) }));

/** Closes every sheet, for actions that finish what the sheets were for. */
export const closeAllSheets = () => useUi.setState({ sheet: null, sheetStack: [] });

/** Whether a sheet is open, and how: underneath another one, or on top of one (`over`). */
export function useSheet(name: Exclude<Sheet, null>) {
  const top = useUi((s) => s.sheet === name);
  const behind = useUi((s) => s.sheetStack.includes(name));
  const over = useUi((s) => s.sheet === name && s.sheetStack.length > 0);
  return { open: top || behind, behind, over };
}
