import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/App";
import { ShapeProvider } from "@/lib/shape-context";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ShapeProvider defaultShape="rounded">
      <App />
    </ShapeProvider>
  </React.StrictMode>,
);
