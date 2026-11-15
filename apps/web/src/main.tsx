import "@fontsource-variable/noto-sans";
import "@fontsource-variable/noto-sans-devanagari";
import "@fontsource-variable/noto-sans-bengali";
import "@fontsource-variable/noto-sans-tamil";
import "@fontsource-variable/noto-sans-telugu";
import "@fontsource-variable/noto-sans-kannada";
import "@fontsource-variable/noto-sans-gujarati";
import "@fontsource-variable/noto-sans-gurmukhi";
import "@fontsource-variable/noto-sans-malayalam";
import "@fontsource-variable/noto-sans-oriya";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { connect } from "./lib/session";
import { registerPWA } from "./pwa";

// TanStack Query is for REST (health now; audit/admin later). The live conversation is the socket + Zustand.
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

connect(); // once, outside React, so StrictMode's double render does not open two sessions
registerPWA();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
