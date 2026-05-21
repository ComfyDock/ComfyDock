import { App } from "@/App";
import { ShapeProvider } from "@/lib/shape-context";
import { configureStudioRuntime, type StudioRuntimeConfig } from "@/lib/runtime-config";
import "./styles.css";

export type { StudioRuntimeConfig } from "@/lib/runtime-config";
export { configureStudioRuntime } from "@/lib/runtime-config";

export function StudioApp({ config }: { config?: Partial<StudioRuntimeConfig> }) {
  configureStudioRuntime(config);
  return (
    <ShapeProvider defaultShape="rounded">
      <App />
    </ShapeProvider>
  );
}
