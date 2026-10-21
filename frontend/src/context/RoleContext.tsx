"use client";

import React, { createContext, useContext, useMemo, useState } from "react";

export type ClientRoleId = "prop_firm_admin" | "quant_researcher" | "funded_trader";

export interface RoleMetadata {
  roleId: ClientRoleId;
  title: string;
  segment: string;
  focusSummary: string;
  allowedRoutes: string[];
  canModifyRiskParameters: boolean;
  canTriggerKillSwitch: boolean;
  canExecuteTraderOrders: boolean;
  canAccessSurveillanceAndDealingDesk: boolean;
  canRunWalkForwardAndSql: boolean;
  executionPermission: "none" | "control_plane_gated";
}

export const CLIENT_ROLE_PROFILES: Record<ClientRoleId, RoleMetadata> = {
  prop_firm_admin: {
    roleId: "prop_firm_admin",
    title: "B2B Enterprise Prop Operator",
    segment: "B2B Prop Firm & Risk Desk",
    focusSummary:
      "Multi-account surveillance, real-time liquidation engine, Sybil/latency-arbitrage detection, and B-Book to A-Book smart dealing desk copier.",
    allowedRoutes: [
      "/",
      "/listings",
      "/market",
      "/trade",
      "/trade/cockpit",
      "/trade/depth-dom",
      "/trade/blotter",
      "/trade/journal",
      "/control",
      "/control/risk-hud",
      "/control/rulebook",
      "/control/surveillance",
      "/control/proctoring",
      "/control/dealing-desk",
      "/research",
      "/research/central-node",
      "/research/walk-forward",
      "/research/microstructure",
      "/research/registry",
      "/data",
      "/data/lakehouse",
      "/data/pipelines",
      "/data/governance",
      "/data/features-100",
    ],
    canModifyRiskParameters: true,
    canTriggerKillSwitch: true,
    canExecuteTraderOrders: true,
    canAccessSurveillanceAndDealingDesk: true,
    canRunWalkForwardAndSql: true,
    executionPermission: "control_plane_gated",
  },
  quant_researcher: {
    roleId: "quant_researcher",
    title: "Institutional Quant Researcher",
    segment: "Institutional Quant / Hedge Fund",
    focusSummary:
      "Purged & embargoed walk-forward evaluation (EXP-001), Kyle's Lambda & VPIN feature stores, and causal model training lifecycle (execution_permission: none).",
    allowedRoutes: [
      "/",
      "/listings",
      "/market",
      "/research",
      "/research/central-node",
      "/research/walk-forward",
      "/research/microstructure",
      "/research/registry",
      "/models",
      "/experiments",
      "/matrix",
      "/data",
      "/data/lakehouse",
      "/data/pipelines",
      "/data/governance",
      "/data/features-100",
      "/warehouse",
    ],
    canModifyRiskParameters: false,
    canTriggerKillSwitch: false,
    canExecuteTraderOrders: false,
    canAccessSurveillanceAndDealingDesk: false,
    canRunWalkForwardAndSql: true,
    executionPermission: "none",
  },
  funded_trader: {
    roleId: "funded_trader",
    title: "Challenge & Funded Trader",
    segment: "Prop Challenge & Open-Market Trader",
    focusSummary:
      "Live execution cockpit, Depth of Market (DOM) ladder, Dynamic Remaining-Room HUD (cushion to 4% daily loss and 8% trailing DD), and pre-trade bracket order desk.",
    allowedRoutes: [
      "/",
      "/listings",
      "/market",
      "/trade",
      "/trade/cockpit",
      "/trade/depth-dom",
      "/trade/blotter",
      "/trade/journal",
    ],
    canModifyRiskParameters: false,
    canTriggerKillSwitch: false,
    canExecuteTraderOrders: true,
    canAccessSurveillanceAndDealingDesk: false,
    canRunWalkForwardAndSql: false,
    executionPermission: "control_plane_gated",
  },
};

export interface RoleContextValue {
  role: ClientRoleId;
  setRole: (role: ClientRoleId) => void;
  profile: RoleMetadata;
  canAccessRoute: (route: string) => boolean;
}

const RoleContext = createContext<RoleContextValue | null>(null);

export function RoleProvider({
  initialRole = "prop_firm_admin",
  children,
}: {
  initialRole?: ClientRoleId;
  children: React.ReactNode;
}) {
  const [role, setRole] = useState<ClientRoleId>(initialRole);
  const profile = CLIENT_ROLE_PROFILES[role];

  const value = useMemo<RoleContextValue>(
    () => ({
      role,
      setRole,
      profile,
      canAccessRoute: (route: string) => {
        const clean = route.trim() || "/";
        return profile.allowedRoutes.some(
          (allowed) => clean === allowed || (allowed !== "/" && clean.startsWith(allowed))
        );
      },
    }),
    [profile, role]
  );

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRoleContext(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) {
    return {
      role: "prop_firm_admin",
      setRole: () => {},
      profile: CLIENT_ROLE_PROFILES.prop_firm_admin,
      canAccessRoute: () => true,
    };
  }
  return ctx;
}

