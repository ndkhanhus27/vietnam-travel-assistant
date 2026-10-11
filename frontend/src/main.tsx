import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AppearanceProvider } from "./appearance/AppearanceProvider";
import { AuthProvider } from "./auth/AuthProvider";
import { LocaleProvider } from "./locale/LocaleProvider";
import "antd/dist/reset.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AppearanceProvider>
        <LocaleProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </LocaleProvider>
      </AppearanceProvider>
    </BrowserRouter>
  </StrictMode>,
);
