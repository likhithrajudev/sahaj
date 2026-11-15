import "@fontsource-variable/anek-latin";
import "@fontsource-variable/anek-devanagari";
import "@fontsource-variable/anek-bangla";
import "@fontsource-variable/anek-tamil";
import "@fontsource-variable/anek-telugu";
import "@fontsource-variable/anek-kannada";
import "@fontsource-variable/anek-malayalam";
import "@fontsource-variable/anek-gujarati";
import "@fontsource-variable/anek-gurmukhi";
import "@fontsource-variable/anek-odia";
import "@fontsource-variable/noto-naskh-arabic"; // Urdu, Kashmiri, Sindhi
import "@fontsource-variable/jetbrains-mono"; // reference numbers
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { connect } from "./lib/session";
import { applyTheme } from "./lib/theme";
import { registerPWA } from "./pwa";

// TanStack Query is for REST (health now; audit/admin later). The live conversation is the socket + Zustand.
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

applyTheme();
connect(); // once, outside React, so StrictMode's double render does not open two sessions
registerPWA();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
