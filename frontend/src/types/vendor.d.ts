declare module "lucide-react" {
  import type { SVGProps } from "react";
  export type LucideIcon = (props: SVGProps<SVGSVGElement> & { size?: number | string }) => JSX.Element;
  export const Activity: LucideIcon;
  export const Wifi: LucideIcon;
  export const ShieldCheck: LucideIcon;
  export const AlertTriangle: LucideIcon;
}

