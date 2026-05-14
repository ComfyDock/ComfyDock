import type React from "react";

export type IconComponent = React.ComponentType<{
  size?: number | string;
  strokeWidth?: number | string;
  className?: string;
}>;
