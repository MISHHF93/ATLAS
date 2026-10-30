"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CLIENT_ROLE_PROFILES,
  RoleProvider,
  useRoleContext,
  type ClientRoleId,
} from "../../context/RoleContext";
import { AssetMarkLegend, GuideIcon, markColor } from "../shell/guideIcons";
import { type LiveCandlePoint } from "./liveTypes";
import { tradingViewUrl } from "./AtlasChart";
import { DeskChart } from "./DeskChart";
import { useFeedQuotes } from "../../lib/feedQuotes";
import { AssetCard, AssetTable } from "./AssetCard";
import { AiDailyInvestmentBriefPanel } from "./AiDailyInvestmentBriefPanel";
import { NavLink } from "../../nav/NavLink";

export type AuthenticAssetCategory =
  | "metals"
  | "etfs"
  | "bonds"
  | "stocks"
  | "futures"
  | "fx"
  | "crypto";

export interface Module02ListingPacket {
  symbol: string;
  name: string;
  track: "open_market" | "competition";
  category: AuthenticAssetCategory;
  subCategory: string;
  provider: "databento" | "polygon" | "ccxt_pro" | "coinbase" | "hyperliquid";
  venue: string;
  price: number;
  prevPrice: number;
  changePct: number;
  vpin: number;
  ofi: number;
  kylesLambda: number;
  spreadBps: number;
  latencyMs: number;
  regime: string;
  bidDepthTop5: number[];
  askDepthTop5: number[];
  flash: "up" | "down" | "none";
  executionPermission: "none";
  issuer?: string;
  isin?: string;
  cusip?: string;
  secCik?: string;
  exchangeMic?: string;
  jurisdiction?: "US" | "CA" | "EU" | "GLOBAL";
  nativeCurrency?: "USD" | "CAD";
  expenseRatioBps?: number | null;
  custodyForm?: string;
  disclosureNote?: string;
  marketId?: string;
  marketName?: string;
  marketOpen?: boolean;
  marketLabel?: string;
  marketCountdown?: string;
}

function makePacket(
  symbol: string,
  name: string,
  category: AuthenticAssetCategory,
  subCategory: string,
  venue: string,
  track: "open_market" | "competition" = "open_market",
  provider: Module02ListingPacket["provider"] = "databento",
  spreadBps = 1.4,
  meta?: Partial<Module02ListingPacket>
): Module02ListingPacket {
  return {
    symbol,
    name,
    track,
    category,
    subCategory,
    provider,
    venue,
    price: 0, // displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 0,
    vpin: 0.24,
    ofi: 0.16,
    kylesLambda: 0.0012,
    spreadBps,
    latencyMs: 6.8,
    regime: "Compression",
    bidDepthTop5: [150, 120, 95, 80, 60],
    askDepthTop5: [130, 105, 88, 72, 54],
    flash: "none",
    executionPermission: "none",
    issuer: meta?.issuer ?? "Exchange / Regulated Sponsor",
    isin: meta?.isin,
    cusip: meta?.cusip,
    secCik: meta?.secCik,
    exchangeMic: meta?.exchangeMic ?? (symbol.endsWith(".TO") ? "XTSE" : "ARCX"),
    jurisdiction: meta?.jurisdiction ?? (symbol.endsWith(".TO") ? "CA" : "US"),
    nativeCurrency: meta?.nativeCurrency ?? (symbol.endsWith(".TO") ? "CAD" : "USD"),
    expenseRatioBps: meta?.expenseRatioBps ?? null,
    custodyForm: meta?.custodyForm ?? "Direct Regulated Listing",
    disclosureNote:
      meta?.disclosureNote ??
      "Verified instrument identity (ISO 6166 ISIN / SEC CIK / SEDAR+). Identity verification does not imply investment safety.",
  };
}

const INITIAL_MODULE02_LISTINGS: Module02ListingPacket[] = [
  // Feature 2: Precious Metals Catalog — Gold, Silver, Platinum, Palladium (Futures, Spot, Certificates/ETRs, ETPs)
  makePacket("GC", "Gold Futures — COMEX Front Month (100 troy oz)", "metals", "Precious Metals Future", "CME Globex · COMEX Metals", "open_market", "databento", 0.8, {
    issuer: "CME Group / COMEX",
    exchangeMic: "XCEC",
    custodyForm: "Futures Contract (100 troy oz COMEX Warrant)",
    disclosureNote: "Exchange-traded futures contract subject to margin and roll risk (NI 93-101).",
  }),
  makePacket("MGC", "Micro Gold Futures — COMEX (10 troy oz)", "metals", "Precious Metals Future", "CME Globex · COMEX Metals", "open_market", "databento", 1.0, {
    issuer: "CME Group / COMEX",
    exchangeMic: "XCEC",
    custodyForm: "Futures Contract (10 troy oz Micro)",
  }),
  makePacket("SI", "Silver Futures — COMEX Front Month (5,000 troy oz)", "metals", "Precious Metals Future", "CME Globex · COMEX Metals", "open_market", "databento", 1.2, {
    issuer: "CME Group / COMEX",
    exchangeMic: "XCEC",
    custodyForm: "Futures Contract (5,000 troy oz COMEX Warrant)",
  }),
  makePacket("PL", "Platinum Futures — NYMEX Front Month (50 troy oz)", "metals", "Precious Metals Future", "CME Globex · NYMEX Metals", "open_market", "databento", 1.8, {
    issuer: "CME Group / NYMEX",
    exchangeMic: "XNYM",
    custodyForm: "Futures Contract (50 troy oz NYMEX Warrant)",
  }),
  makePacket("PA", "Palladium Futures — NYMEX Front Month (100 troy oz)", "metals", "Precious Metals Future", "CME Globex · NYMEX Metals", "open_market", "databento", 2.4, {
    issuer: "CME Group / NYMEX",
    exchangeMic: "XNYM",
    custodyForm: "Futures Contract (100 troy oz NYMEX Warrant)",
  }),
  makePacket("GLD", "SPDR Gold Shares Physical Bullion Trust ETF", "metals", "Physical Gold ETP", "NYSE Arca · XARC", "open_market", "databento", 1.0, {
    issuer: "World Gold Trust Services / State Street",
    isin: "US78463V1070",
    cusip: "78463V107",
    secCik: "0001222333",
    exchangeMic: "ARCX",
    expenseRatioBps: 40,
    custodyForm: "Physical Allocated LBMA London Good Delivery Bars (HSBC Vault)",
  }),
  makePacket("SLV", "iShares Silver Trust Physical Bullion ETF", "metals", "Physical Silver ETP", "NYSE Arca · XARC", "open_market", "databento", 1.4, {
    issuer: "BlackRock / iShares Delaware Trust Sponsor",
    isin: "US46428Q1094",
    cusip: "46428Q109",
    secCik: "0001330568",
    exchangeMic: "ARCX",
    expenseRatioBps: 50,
    custodyForm: "Physical Allocated LBMA Silver Bullion (JPMorgan London/NY Vaults)",
  }),
  makePacket("PPLT", "abrdn Physical Platinum Shares ETF", "metals", "Physical Platinum ETP", "NYSE Arca · XARC", "open_market", "databento", 1.9, {
    issuer: "abrdn Precious Metals Trust",
    isin: "US0032601066",
    cusip: "003260106",
    secCik: "0001469510",
    exchangeMic: "ARCX",
    expenseRatioBps: 60,
    custodyForm: "Physical Allocated LPPM Platinum Plates/Ingots (JPMorgan London/Zurich)",
  }),
  makePacket("PALL", "abrdn Physical Palladium Shares ETF", "metals", "Physical Palladium ETP", "NYSE Arca · XARC", "open_market", "databento", 2.2, {
    issuer: "abrdn Precious Metals Trust",
    isin: "US0032621023",
    cusip: "003262102",
    secCik: "0001469511",
    exchangeMic: "ARCX",
    expenseRatioBps: 60,
    custodyForm: "Physical Allocated LPPM Palladium Ingots (JPMorgan London/Zurich)",
  }),
  makePacket("MNT.TO", "Royal Canadian Mint — Canadian Gold Reserves ETR", "metals", "Crown Corp Gold Certificate ETR", "Toronto Stock Exchange · XTSE", "open_market", "databento", 1.5, {
    issuer: "Royal Canadian Mint (Federal Crown Corporation)",
    isin: "CA7800811053",
    cusip: "780081105",
    exchangeMic: "XTSE",
    jurisdiction: "CA",
    nativeCurrency: "CAD",
    expenseRatioBps: 35,
    custodyForm: "Direct Beneficial Title to 99.99% Bullion at Royal Canadian Mint Ottawa Vault",
    disclosureNote: "Exchange-Traded Receipt (ETR) backed by sovereign Crown Corporation custody under Royal Canadian Mint Act.",
  }),
  makePacket("MNS.TO", "Royal Canadian Mint — Canadian Silver Reserves ETR", "metals", "Crown Corp Silver Certificate ETR", "Toronto Stock Exchange · XTSE", "open_market", "databento", 1.8, {
    issuer: "Royal Canadian Mint (Federal Crown Corporation)",
    isin: "CA7800813034",
    cusip: "780081303",
    exchangeMic: "XTSE",
    jurisdiction: "CA",
    nativeCurrency: "CAD",
    expenseRatioBps: 45,
    custodyForm: "Direct Beneficial Title to 99.9% Silver Bullion at Royal Canadian Mint Ottawa Vault",
  }),
  makePacket("PHYS", "Sprott Physical Gold Trust", "metals", "Allocated Physical Gold Trust", "NYSE Arca / TSX · ARCX", "open_market", "databento", 1.2, {
    issuer: "Sprott Asset Management LP",
    isin: "CA85207H1047",
    cusip: "85207H104",
    secCik: "0001477039",
    exchangeMic: "ARCX",
    jurisdiction: "CA",
    expenseRatioBps: 41,
    custodyForm: "Fully Allocated London Good Delivery Gold Bars at Royal Canadian Mint",
  }),
  makePacket("PSLV", "Sprott Physical Silver Trust", "metals", "Allocated Physical Silver Trust", "NYSE Arca / TSX · ARCX", "open_market", "databento", 1.4, {
    issuer: "Sprott Asset Management LP",
    isin: "CA85207K1075",
    cusip: "85207K107",
    secCik: "0001494728",
    exchangeMic: "ARCX",
    jurisdiction: "CA",
    expenseRatioBps: 60,
    custodyForm: "Fully Allocated Good Delivery Silver Bars at Royal Canadian Mint",
  }),

  // Feature 3: ETF and Fund Intelligence — Broad Equity Index, Sector, Semiconductor, Real Estate & Canadian ETFs
  makePacket("SPY", "SPDR S&P 500 ETF Trust", "etfs", "US Broad Index ETF", "NYSE Arca · ARCX", "open_market", "databento", 0.9, {
    issuer: "State Street Global Advisors (SSGA)",
    isin: "US78462F1030",
    cusip: "78462F103",
    secCik: "0000884394",
    exchangeMic: "ARCX",
    expenseRatioBps: 9.45,
    custodyForm: "Unit Investment Trust (Full Physical Replication)",
  }),
  makePacket("QQQ", "Invesco QQQ Trust (Nasdaq-100)", "etfs", "US Broad Index ETF", "Nasdaq · XNAS", "open_market", "databento", 1.1, {
    issuer: "Invesco Capital Management LLC",
    isin: "US46090E1038",
    cusip: "46090E103",
    secCik: "0001067839",
    exchangeMic: "XNAS",
    expenseRatioBps: 20,
    custodyForm: "Unit Investment Trust (Full Physical Replication)",
  }),
  makePacket("IWM", "iShares Russell 2000 Small-Cap ETF", "etfs", "US Small-Cap Index ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.3, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642876555",
    cusip: "464287655",
    secCik: "0001100663",
    exchangeMic: "ARCX",
    expenseRatioBps: 19,
  }),
  makePacket("DIA", "SPDR Dow Jones Industrial Average ETF", "etfs", "US Broad Index ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.2, {
    issuer: "State Street Global Advisors (SSGA)",
    isin: "US78467X1019",
    cusip: "78467X101",
    secCik: "0001041130",
    exchangeMic: "ARCX",
    expenseRatioBps: 16,
  }),
  makePacket("VOO", "Vanguard S&P 500 ETF", "etfs", "US Broad Index ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.0, {
    issuer: "The Vanguard Group, Inc.",
    isin: "US9229083632",
    cusip: "922908363",
    secCik: "0000036405",
    exchangeMic: "ARCX",
    expenseRatioBps: 3,
  }),
  makePacket("VTI", "Vanguard Total Stock Market ETF", "etfs", "US Broad Index ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.1, {
    issuer: "The Vanguard Group, Inc.",
    isin: "US9229087690",
    cusip: "922908769",
    secCik: "0000036405",
    exchangeMic: "ARCX",
    expenseRatioBps: 3,
  }),
  makePacket("XIU.TO", "iShares S&P/TSX 60 Index ETF", "etfs", "Canadian Flagship Equity ETF", "Toronto Stock Exchange · XTSE", "open_market", "databento", 1.1, {
    issuer: "BlackRock Asset Management Canada Limited",
    isin: "CA4643001017",
    cusip: "464300101",
    exchangeMic: "XTSE",
    jurisdiction: "CA",
    nativeCurrency: "CAD",
    expenseRatioBps: 18,
    custodyForm: "NI 81-102 Mutual Fund Trust ETF (Full Physical Replication)",
  }),
  makePacket("XLK", "Technology Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.2, {
    issuer: "SSGA Funds Management, Inc.",
    isin: "US81369Y8030",
    cusip: "81369Y803",
    secCik: "0001064641",
    expenseRatioBps: 9,
  }),
  makePacket("XLF", "Financial Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.2, {
    issuer: "SSGA Funds Management, Inc.",
    isin: "US81369Y6059",
    cusip: "81369Y605",
    secCik: "0001064641",
    expenseRatioBps: 9,
  }),
  makePacket("XLE", "Energy Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.3, {
    issuer: "SSGA Funds Management, Inc.",
    isin: "US81369Y5069",
    cusip: "81369Y506",
    secCik: "0001064641",
    expenseRatioBps: 9,
  }),
  makePacket("XLV", "Health Care Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.2, {
    issuer: "SSGA Funds Management, Inc.",
    isin: "US81369Y2090",
    cusip: "81369Y209",
    secCik: "0001064641",
    expenseRatioBps: 9,
  }),
  makePacket("XLI", "Industrial Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.2, {
    issuer: "SSGA Funds Management, Inc.",
    isin: "US81369Y7040",
    cusip: "81369Y704",
    secCik: "0001064641",
    expenseRatioBps: 9,
  }),
  makePacket("SOXX", "iShares Semiconductor ETF", "etfs", "Semiconductor ETF", "Nasdaq · XNAS", "open_market", "databento", 1.5, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642875235",
    cusip: "464287523",
    secCik: "0001100663",
    exchangeMic: "XNAS",
    expenseRatioBps: 35,
  }),
  makePacket("SMH", "VanEck Semiconductor ETF", "etfs", "Semiconductor ETF", "Nasdaq · XNAS", "open_market", "databento", 1.4, {
    issuer: "VanEck Associates Corporation",
    isin: "US92189F1066",
    cusip: "92189F106",
    secCik: "0001137360",
    exchangeMic: "XNAS",
    expenseRatioBps: 35,
  }),
  makePacket("VNQ", "Vanguard Real Estate Index Fund ETF", "etfs", "Real Estate REIT ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.4, {
    issuer: "The Vanguard Group, Inc.",
    isin: "US9229085538",
    cusip: "922908553",
    secCik: "0000036405",
    expenseRatioBps: 13,
  }),
  makePacket("ARKK", "ARK Innovation Active ETF", "etfs", "Thematic Growth ETF", "NYSE Arca · ARCX", "open_market", "databento", 2.0, {
    issuer: "ARK Investment Management LLC",
    isin: "US00214Q1040",
    cusip: "00214Q104",
    secCik: "0001579982",
    expenseRatioBps: 75,
  }),

  // Feature 4: Bonds & Cash Equivalents (Treasury ETFs, Corporate Bond ETFs, T-Bill Money Market ETFs & Rate Futures)
  makePacket("TLT", "iShares 20+ Year US Treasury Bond ETF", "bonds", "Long-Duration Sovereign Bond ETF", "Nasdaq · XNAS", "open_market", "databento", 1.1, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642874329",
    cusip: "464287432",
    secCik: "0001100663",
    exchangeMic: "XNAS",
    expenseRatioBps: 15,
    custodyForm: "US Treasury Bonds (Effective Duration ~16.2y)",
  }),
  makePacket("IEF", "iShares 7-10 Year US Treasury Bond ETF", "bonds", "Intermediate Sovereign Bond ETF", "Nasdaq · XNAS", "open_market", "databento", 1.1, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642874402",
    cusip: "464287440",
    secCik: "0001100663",
    exchangeMic: "XNAS",
    expenseRatioBps: 15,
    custodyForm: "US Treasury Notes (Effective Duration ~7.4y)",
  }),
  makePacket("SHY", "iShares 1-3 Year US Treasury Bond ETF", "bonds", "Short-Duration Sovereign Bond ETF", "Nasdaq · XNAS", "open_market", "databento", 0.9, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642874576",
    cusip: "464287457",
    secCik: "0001100663",
    exchangeMic: "XNAS",
    expenseRatioBps: 15,
    custodyForm: "Short US Treasury Notes (Effective Duration ~1.9y)",
  }),
  makePacket("BIL", "SPDR Bloomberg 1-3 Month T-Bill ETF (Cash Equivalent)", "bonds", "Cash Equivalent / Ultrashort T-Bill ETF", "NYSE Arca · ARCX", "open_market", "databento", 0.5, {
    issuer: "SSGA Funds Management, Inc.",
    isin: "US78468R6633",
    cusip: "78468R663",
    secCik: "0001064642",
    exchangeMic: "ARCX",
    expenseRatioBps: 13.5,
    custodyForm: "Zero-Coupon US Treasury Bills (1-3 Month Maturity, Duration ~0.12y)",
  }),
  makePacket("SGOV", "iShares 0-3 Month Treasury Bond ETF (Cash Equivalent)", "bonds", "Cash Equivalent / Ultrashort T-Bill ETF", "NYSE Arca · ARCX", "open_market", "databento", 0.5, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US46436E7186",
    cusip: "46436E718",
    secCik: "0001100663",
    exchangeMic: "ARCX",
    expenseRatioBps: 9,
    custodyForm: "US Treasury Bills <= 3 Months Maturity (Duration ~0.10y)",
  }),
  makePacket("SHV", "iShares Short Treasury Bond ETF (Cash Equivalent)", "bonds", "Cash Equivalent / Short T-Bill ETF", "Nasdaq · XNAS", "open_market", "databento", 0.6, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642886794",
    cusip: "464288679",
    secCik: "0001100663",
    exchangeMic: "XNAS",
    expenseRatioBps: 15,
    custodyForm: "US Treasury Obligations <= 1 Year Maturity (Duration ~0.29y)",
  }),
  makePacket("AGG", "iShares Core US Aggregate Bond ETF", "bonds", "Core Investment-Grade Bond ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.0, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642872265",
    cusip: "464287226",
    secCik: "0001100663",
    expenseRatioBps: 3,
  }),
  makePacket("BND", "Vanguard Total Bond Market ETF", "bonds", "Core Investment-Grade Bond ETF", "Nasdaq · XNAS", "open_market", "databento", 1.0, {
    issuer: "The Vanguard Group, Inc.",
    isin: "US9219378356",
    cusip: "921937835",
    secCik: "0000794105",
    exchangeMic: "XNAS",
    expenseRatioBps: 3,
  }),
  makePacket("LQD", "iShares iBoxx Investment Grade Corporate Bond ETF", "bonds", "Investment-Grade Corporate Bond ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.2, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642872422",
    cusip: "464287242",
    secCik: "0001100663",
    expenseRatioBps: 14,
  }),
  makePacket("HYG", "iShares iBoxx High Yield Corporate Bond ETF", "bonds", "High-Yield Corporate Bond ETF", "NYSE Arca · ARCX", "open_market", "databento", 1.4, {
    issuer: "BlackRock Fund Advisors (iShares)",
    isin: "US4642885135",
    cusip: "464288513",
    secCik: "0001100663",
    expenseRatioBps: 49,
  }),
  makePacket("ZN", "10-Year US Treasury Note Futures", "bonds", "CBOT Sovereign Rate Future", "CME Globex · CBOT", "open_market", "databento", 0.6, {
    issuer: "CME Group / CBOT",
    exchangeMic: "XCBT",
    custodyForm: "CBOT $100,000 Face Value 10Y Treasury Note Future",
  }),
  makePacket("ZB", "30-Year US Treasury Bond Futures", "bonds", "CBOT Sovereign Rate Future", "CME Globex · CBOT", "open_market", "databento", 0.8, {
    issuer: "CME Group / CBOT",
    exchangeMic: "XCBT",
    custodyForm: "CBOT $100,000 Face Value 30Y Treasury Bond Future",
  }),

  // CME Globex Futures — Equity Index, Energy & Currency Futures
  makePacket("ES", "E-mini S&P 500 Futures (Front Month)", "futures", "CME Equity Index Future", "CME Globex · GLBX.MDP3", "open_market", "databento", 0.5, {
    issuer: "CME Group",
    exchangeMic: "XCME",
  }),
  makePacket("NQ", "E-mini Nasdaq-100 Futures (Front Month)", "futures", "CME Equity Index Future", "CME Globex · GLBX.MDP3", "open_market", "databento", 0.6, {
    issuer: "CME Group",
    exchangeMic: "XCME",
  }),
  makePacket("YM", "E-mini Dow ($5) Futures", "futures", "CME Equity Index Future", "CME Globex · CBOT", "open_market", "databento", 0.8, {
    issuer: "CME Group / CBOT",
    exchangeMic: "XCBT",
  }),
  makePacket("RTY", "E-mini Russell 2000 Futures", "futures", "CME Equity Index Future", "CME Globex · GLBX.MDP3", "open_market", "databento", 1.0, {
    issuer: "CME Group",
    exchangeMic: "XCME",
  }),
  makePacket("CL", "WTI Light Sweet Crude Oil Futures", "futures", "NYMEX Energy Future", "CME Globex · NYMEX", "open_market", "databento", 0.9, {
    issuer: "CME Group / NYMEX",
    exchangeMic: "XNYM",
  }),
  makePacket("MCL", "Micro WTI Crude Oil Futures", "futures", "NYMEX Energy Future", "CME Globex · NYMEX", "open_market", "databento", 1.1, {
    issuer: "CME Group / NYMEX",
    exchangeMic: "XNYM",
  }),
  makePacket("NG", "Henry Hub Natural Gas Futures", "futures", "NYMEX Energy Future", "CME Globex · NYMEX", "open_market", "databento", 1.6, {
    issuer: "CME Group / NYMEX",
    exchangeMic: "XNYM",
  }),
  makePacket("6E", "Euro FX Futures (CME Globex)", "futures", "CME Currency Future", "CME Globex · FX", "open_market", "databento", 0.7, {
    issuer: "CME Group",
    exchangeMic: "XCME",
  }),
  makePacket("6J", "Japanese Yen Futures (CME Globex)", "futures", "CME Currency Future", "CME Globex · FX", "open_market", "databento", 0.8, {
    issuer: "CME Group",
    exchangeMic: "XCME",
  }),

  // Official Central-Bank & Interbank Spot FX
  makePacket("EUR_USD", "Euro / US Dollar Spot FX (ECB & Interbank)", "fx", "G10 Spot FX", "ECB SDMX & Global FX", "open_market", "databento", 0.6, {
    issuer: "European Central Bank (ECB) / Federal Reserve",
    exchangeMic: "XOFF",
    jurisdiction: "EU",
  }),
  makePacket("USD_CAD", "US Dollar / Canadian Dollar Spot FX (BoC Valet)", "fx", "G10 Spot FX", "Bank of Canada & Global FX", "open_market", "databento", 0.7, {
    issuer: "Bank of Canada (Valet FXUSDCAD)",
    exchangeMic: "XOFF",
    jurisdiction: "CA",
    nativeCurrency: "CAD",
  }),

  // Feature 4: SEC-Verified US & SEDAR+ Verified Canadian Public Equities
  makePacket("NVDA", "NVIDIA Corp. (SEC CIK 0001045810)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.5, {
    issuer: "NVIDIA Corporation",
    isin: "US67066G1040",
    cusip: "67066G104",
    secCik: "0001045810",
    exchangeMic: "XNAS",
  }),
  makePacket("AAPL", "Apple Inc. (SEC CIK 0000320193)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "databento", 1.2, {
    issuer: "Apple Inc.",
    isin: "US0378331005",
    cusip: "037833100",
    secCik: "0000320193",
    exchangeMic: "XNAS",
  }),
  makePacket("MSFT", "Microsoft Corp. (SEC CIK 0000789019)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.2, {
    issuer: "Microsoft Corporation",
    isin: "US5949181045",
    cusip: "594918104",
    secCik: "0000789019",
    exchangeMic: "XNAS",
  }),
  makePacket("AMZN", "Amazon.com Inc.", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.3, {
    issuer: "Amazon.com, Inc.",
    isin: "US0231351067",
    cusip: "023135106",
    secCik: "0001018724",
    exchangeMic: "XNAS",
  }),
  makePacket("META", "Meta Platforms Inc.", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.4, {
    issuer: "Meta Platforms, Inc.",
    isin: "US30303M1027",
    cusip: "30303M102",
    secCik: "0001326801",
    exchangeMic: "XNAS",
  }),
  makePacket("GOOGL", "Alphabet Inc. Class A", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.3, {
    issuer: "Alphabet Inc.",
    isin: "US02079K3059",
    cusip: "02079K305",
    secCik: "0001652044",
    exchangeMic: "XNAS",
  }),
  makePacket("TSLA", "Tesla Inc. (SEC CIK 0001318605)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 2.0, {
    issuer: "Tesla, Inc.",
    isin: "US88160R1014",
    cusip: "88160R101",
    secCik: "0001318605",
    exchangeMic: "XNAS",
  }),
  makePacket("AMD", "Advanced Micro Devices Inc.", "stocks", "US Semiconductor Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.7, {
    issuer: "Advanced Micro Devices, Inc.",
    isin: "US0079031078",
    cusip: "007903107",
    secCik: "0000002488",
    exchangeMic: "XNAS",
  }),
  makePacket("AVGO", "Broadcom Inc.", "stocks", "US Semiconductor Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.6, {
    issuer: "Broadcom Inc.",
    isin: "US11135F1012",
    cusip: "11135F101",
    secCik: "0001730168",
    exchangeMic: "XNAS",
  }),
  makePacket("JPM", "JPMorgan Chase & Co.", "stocks", "US Money-Center Bank", "NYSE · XNYS", "open_market", "databento", 1.2, {
    issuer: "JPMorgan Chase & Co.",
    isin: "US46625H1005",
    cusip: "46625H100",
    secCik: "0000019617",
    exchangeMic: "XNYS",
  }),
  makePacket("GS", "The Goldman Sachs Group Inc.", "stocks", "US Investment Bank", "NYSE · XNYS", "open_market", "databento", 1.4, {
    issuer: "The Goldman Sachs Group, Inc.",
    isin: "US38141G1040",
    cusip: "38141G104",
    secCik: "0000886982",
    exchangeMic: "XNYS",
  }),
  makePacket("LLY", "Eli Lilly and Company", "stocks", "US Pharmaceuticals", "NYSE · XNYS", "open_market", "databento", 1.5, {
    issuer: "Eli Lilly and Company",
    isin: "US5324571083",
    cusip: "532457108",
    secCik: "0000059478",
    exchangeMic: "XNYS",
  }),
  makePacket("XOM", "Exxon Mobil Corporation", "stocks", "US Integrated Energy", "NYSE · XNYS", "open_market", "databento", 1.2, {
    issuer: "Exxon Mobil Corporation",
    isin: "US30231G1022",
    cusip: "30231G102",
    secCik: "0000034088",
    exchangeMic: "XNYS",
  }),
  makePacket("RY.TO", "Royal Bank of Canada (TSX / SEDAR+ 00001307)", "stocks", "Canadian Schedule I Bank", "Toronto Stock Exchange · XTSE", "open_market", "databento", 1.2, {
    issuer: "Royal Bank of Canada",
    isin: "CA7800871021",
    cusip: "780087102",
    secCik: "0001000275",
    exchangeMic: "XTSE",
    jurisdiction: "CA",
    nativeCurrency: "CAD",
  }),
  makePacket("SHOP.TO", "Shopify Inc. (TSX / SEDAR+ 00037036)", "stocks", "Canadian Technology Equity", "Toronto Stock Exchange · XTSE", "open_market", "databento", 1.6, {
    issuer: "Shopify Inc.",
    isin: "CA82509L1076",
    cusip: "82509L107",
    secCik: "0001594805",
    exchangeMic: "XTSE",
    jurisdiction: "CA",
    nativeCurrency: "CAD",
  }),

  // Major Liquid Crypto Benchmarks (24/7 Spot & Prop Desk — Pump.fun/Meme Tokens Excluded)
  makePacket("BTC-USD", "Bitcoin Spot / Perpetual Benchmark", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "ccxt_pro", 2.5, {
    issuer: "Bitcoin Network (Regulated Spot Exchanges)",
    exchangeMic: "XOFF",
    jurisdiction: "GLOBAL",
  }),
  makePacket("ETH-USD", "Ethereum Spot / Perpetual Benchmark", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 3.0, {
    issuer: "Ethereum Network (Regulated Spot Exchanges)",
    exchangeMic: "XOFF",
    jurisdiction: "GLOBAL",
  }),
  makePacket("SOL-USD", "Solana Spot / Perpetual Benchmark", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "hyperliquid", 3.8, {
    issuer: "Solana Network (Regulated Spot Exchanges)",
    exchangeMic: "XOFF",
    jurisdiction: "GLOBAL",
  }),
  makePacket("AVAX-USD", "Avalanche Spot / Perpetual", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 4.2, {
    issuer: "Avalanche Network",
    exchangeMic: "XOFF",
    jurisdiction: "GLOBAL",
  }),
  makePacket("LINK-USD", "Chainlink Spot / Perpetual", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 4.0, {
    issuer: "Chainlink Network",
    exchangeMic: "XOFF",
    jurisdiction: "GLOBAL",
  }),
  makePacket("AAVE-USD", "Aave Protocol Spot / Perpetual", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 4.5, {
    issuer: "Aave Governance",
    exchangeMic: "XOFF",
    jurisdiction: "GLOBAL",
  }),
];

const GRAMS_PER_TROY_OZ = 31.1034768;
const TROY_OZ_PER_KG = 1000.0 / GRAMS_PER_TROY_OZ;

function Module02InnerWorkbench() {
  const { role, setRole, profile } = useRoleContext();
  const [categoryFilter, setCategoryFilter] = useState<"all" | "watchlist" | AuthenticAssetCategory>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedSymbol, setSelectedSymbol] = useState<string>("GC");
  const [chartTimeframe, setChartTimeframe] = useState<"1s" | "1m" | "5m" | "15m" | "1h" | "1D">("15m");
  const [listings, setListings] = useState<Module02ListingPacket[]>(INITIAL_MODULE02_LISTINGS);
  const listingsRef = useRef(listings);
  listingsRef.current = listings;
  const [openNowOnly, setOpenNowOnly] = useState(false);
  const [sessionVenues, setSessionVenues] = useState<Array<{
    venue_id: string;
    venue_name: string;
    is_open: boolean;
    status_label?: string;
    look_symbol?: string;
    countdown?: string;
  }>>([]);
  const [displayCurrency, setDisplayCurrency] = useState<"USD" | "CAD">("USD");
  const [metalUnit, setMetalUnit] = useState<"troy_oz" | "gram" | "kg">("troy_oz");
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>([
    "GC",
    "GLD",
    "MNT.TO",
    "SPY",
    "TLT",
    "BIL",
    "NVDA",
  ]);
  const [compareSymbols, setCompareSymbols] = useState<string[]>([
    "GC",
    "GLD",
    "MNT.TO",
    "TLT",
  ]);

  const feedSymbols = useMemo(() => listings.map((l) => l.symbol), [listings]);
  const feedQuotes = useFeedQuotes(feedSymbols);

  const usdCadRate = useMemo(() => {
    const p = feedQuotes["USD_CAD"]?.price;
    return typeof p === "number" && p >= 1.0 && p <= 2.0 ? p : 1.385;
  }, [feedQuotes]);

  const metalSpotMatrix = useMemo(() => {
    const unitFactor =
      metalUnit === "troy_oz"
        ? 1.0
        : metalUnit === "gram"
        ? 1.0 / GRAMS_PER_TROY_OZ
        : TROY_OZ_PER_KG;
    const ccyFactor = displayCurrency === "CAD" ? usdCadRate : 1.0;

    const goldOz = feedQuotes["GC"]?.price ?? 2748.5;
    const silverOz = feedQuotes["SI"]?.price ?? 33.65;
    const platOz = feedQuotes["PL"]?.price ?? 1024.5;
    const pallOz = feedQuotes["PA"]?.price ?? 1185.0;

    return {
      gold: goldOz * unitFactor * ccyFactor,
      silver: silverOz * unitFactor * ccyFactor,
      platinum: platOz * unitFactor * ccyFactor,
      palladium: pallOz * unitFactor * ccyFactor,
      unitLabel: metalUnit === "troy_oz" ? "troy oz" : metalUnit === "gram" ? "gram" : "kg",
    };
  }, [feedQuotes, metalUnit, displayCurrency, usdCadRate]);

  // Live data fetches from backend API on mount; pollModule02Stream refreshes every 2.5s
  useEffect(() => {
    void pollModule02Stream();
  }, []);
  const [catalogView, setCatalogView] = useState<"cards" | "list">("cards");
  const [streamPaused] = useState<boolean>(false);
  const [ringBufferSize, setRingBufferSize] = useState<number>(64);
  const [killSwitchEngaged, setKillSwitchEngaged] = useState<boolean>(false);
  const [rbacBanner, setRbacBanner] = useState<string>(
    "Authentic Assets Catalog · CSA NI 31-103 / NI 81-102 compliant · Pump.fun disabled by product policy · execution_permission: none"
  );
  const [, setFixtureTicks] = useState<LiveCandlePoint[]>([]);
  const fixtureSymbolRef = useRef(selectedSymbol);
  const [feedNote, setFeedNote] = useState("Verified market feed starting");
  const [remainingRoomHud, setRemainingRoomHud] = useState<{
    currentEquityUsd: number;
    startOfDayUsd: number;
    referenceUsd: number;
    dailyFloorUsd: number;
    trailingFloorUsd: number;
    dailyLossLimitPct: number;
    drawdownLimitPct: number;
    drawdownMode: string;
    dailyLossRoomUsd: number;
    dailyLossRoomPct: number;
    trailingDdRoomUsd: number;
    trailingDdRoomPct: number;
  }>({
    currentEquityUsd: 0,
    startOfDayUsd: 0,
    referenceUsd: 0,
    dailyFloorUsd: 0,
    trailingFloorUsd: 0,
    dailyLossLimitPct: 4,
    drawdownLimitPct: 8,
    drawdownMode: "trailing",
    dailyLossRoomUsd: 0,
    dailyLossRoomPct: 0,
    trailingDdRoomUsd: 0,
    trailingDdRoomPct: 0,
  });

  useEffect(() => {
    let alive = true;
    const pullSessions = async () => {
      const symbols = listingsRef.current.map((item) => item.symbol);
      const query = symbols.length ? `?symbols=${encodeURIComponent(symbols.join(","))}` : "";
      try {
        const res = await fetch(`/api/market/sessions${query}`, { cache: "no-store" });
        if (!res.ok) return;
        const body = await res.json();
        if (!alive) return;
        const venues = Array.isArray(body.venues) ? body.venues : [];
        setSessionVenues(venues);
        const by = body.by_symbol && typeof body.by_symbol === "object" ? body.by_symbol : {};
        setListings((prev) => prev.map((item) => {
          const st = by[item.symbol.toUpperCase()];
          if (!st) return item;
          return {
            ...item,
            marketId: st.venue_id,
            marketName: st.venue_name,
            marketOpen: Boolean(st.is_open),
            marketLabel: st.status_label,
            marketCountdown: st.countdown,
          };
        }));
      } catch {
        // Keep the last clock stamp. Prices stay on the feed poll.
      }
    };
    void pullSessions();
    const timer = setInterval(pullSessions, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const pollModule02Stream = useCallback(async () => {
    try {
      const apiBase =
        typeof window !== "undefined" && window.location.port === "3000"
          ? ""
          : "";
      const res = await fetch(`${apiBase}/api/market/module02-snapshot?track=all`, {
        cache: "no-store",
      });
      if (res.ok) {
        const data = await res.json();
        if (typeof data.gateway?.ring_buffer_size === "number") {
          setRingBufferSize(data.gateway.ring_buffer_size);
        }
        if (data.remaining_room_hud) {
          const hud = data.remaining_room_hud;
          setRemainingRoomHud({
            currentEquityUsd: Number(hud.current_equity_usd ?? 0),
            startOfDayUsd: Number(hud.start_of_day_equity_usd ?? 0),
            referenceUsd: Number(hud.high_water_mark_usd ?? 0),
            dailyFloorUsd: Number(hud.daily_floor_usd ?? 0),
            trailingFloorUsd: Number(hud.trailing_floor_usd ?? 0),
            dailyLossLimitPct: Number(hud.daily_loss_limit_pct ?? 4),
            drawdownLimitPct: Number(hud.drawdown_limit_pct ?? 8),
            drawdownMode: String(hud.drawdown_mode ?? "trailing"),
            dailyLossRoomUsd: Number(hud.daily_loss_room_usd ?? 0),
            dailyLossRoomPct: Number(hud.daily_loss_room_pct ?? 0),
            trailingDdRoomUsd: Number(hud.trailing_dd_room_usd ?? 0),
            trailingDdRoomPct: Number(hud.trailing_dd_room_pct ?? 0),
          });
        }
        const origin = String(data.gateway?.feed_origin ?? "labeled_synthetic_fixture");
        const mode = String(data.data_mode ?? (data.gateway?.demo_mode ? "synthetic" : "observed"));
        setFeedNote(
          `${mode} feed · ${origin} · buffer ${data.gateway?.ring_buffer_size ?? "?"} / ${data.gateway?.ring_buffer_maxlen ?? 10000} · venue sessions ${data.gateway?.venue_sessions ?? "unconfigured"} · execution_permission none`
        );
        if (Array.isArray(data.listings) && data.listings.length > 0) {
          setListings((prev) =>
            prev.map((item) => {
              const incoming = data.listings.find(
                (u: { symbol: string }) => String(u.symbol).toUpperCase() === item.symbol
              );
              if (!incoming) return item;
              const nextPrice = Number(incoming.last_price ?? incoming.price ?? item.price);
              const flash: "up" | "down" | "none" =
                nextPrice > item.price ? "up" : nextPrice < item.price ? "down" : item.flash;
              return {
                ...item,
                prevPrice: item.price,
                price: nextPrice,
                vpin: Number(incoming.vpin ?? item.vpin),
                ofi: Number(incoming.ofi ?? item.ofi),
                kylesLambda: Number(incoming.kyles_lambda ?? item.kylesLambda),
                spreadBps: Number(incoming.spread_bps ?? item.spreadBps),
                latencyMs: Number(incoming.latency_ms ?? item.latencyMs),
                regime: String(incoming.regime ?? item.regime),
                bidDepthTop5: Array.isArray(incoming.bid_depth_top5)
                  ? incoming.bid_depth_top5
                  : item.bidDepthTop5,
                askDepthTop5: Array.isArray(incoming.ask_depth_top5)
                  ? incoming.ask_depth_top5
                  : item.askDepthTop5,
                flash,
              };
            })
          );
          return;
        }
      }
    } catch {
      setFeedNote(
        "The market snapshot is unavailable. Prices are frozen at the last received values; no client-side ticks are invented. execution_permission none"
      );
    }
  }, []);

  useEffect(() => {
    void pollModule02Stream();
    if (streamPaused) return;
    const id = setInterval(() => {
      void pollModule02Stream();
    }, 2500);

    let ws: WebSocket | null = null;
    try {
      const wsBase =
        typeof window !== "undefined" && window.location.port === "3000"
          ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
          : typeof window !== "undefined"
          ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
          : "";
      ws = new WebSocket(`${wsBase}/ws/market-stream?symbol=${encodeURIComponent(selectedSymbol)}`);
      ws.onmessage = (evt) => {
        try {
          const incoming = JSON.parse(evt.data);
          if (!incoming || !incoming.symbol) return;
          setListings((prev) =>
            prev.map((item) => {
              if (item.symbol !== String(incoming.symbol).toUpperCase()) return item;
              const nextPrice = Number(incoming.last_price ?? incoming.price ?? item.price);
              const flash: "up" | "down" | "none" =
                nextPrice > item.price ? "up" : nextPrice < item.price ? "down" : item.flash;
              return {
                ...item,
                prevPrice: item.price,
                price: nextPrice,
                vpin: Number(incoming.vpin ?? item.vpin),
                ofi: Number(incoming.ofi ?? item.ofi),
                kylesLambda: Number(incoming.kyles_lambda ?? item.kylesLambda),
                spreadBps: Number(incoming.spread_bps ?? item.spreadBps),
                latencyMs: Number(incoming.latency_ms ?? item.latencyMs),
                regime: String(incoming.regime ?? item.regime),
                bidDepthTop5: Array.isArray(incoming.bid_depth_top5)
                  ? incoming.bid_depth_top5
                  : item.bidDepthTop5,
                askDepthTop5: Array.isArray(incoming.ask_depth_top5)
                  ? incoming.ask_depth_top5
                  : item.askDepthTop5,
                flash,
              };
            })
          );
          if (incoming.remaining_room_hud) {
            const hud = incoming.remaining_room_hud;
            setRemainingRoomHud({
              currentEquityUsd: Number(hud.current_equity_usd ?? 0),
              startOfDayUsd: Number(hud.start_of_day_equity_usd ?? 0),
              referenceUsd: Number(hud.high_water_mark_usd ?? 0),
              dailyFloorUsd: Number(hud.daily_floor_usd ?? 0),
              trailingFloorUsd: Number(hud.trailing_floor_usd ?? 0),
              dailyLossLimitPct: Number(hud.daily_loss_limit_pct ?? 4),
              drawdownLimitPct: Number(hud.drawdown_limit_pct ?? 8),
              drawdownMode: String(hud.drawdown_mode ?? "trailing"),
              dailyLossRoomUsd: Number(hud.daily_loss_room_usd ?? 0),
              dailyLossRoomPct: Number(hud.daily_loss_room_pct ?? 0),
              trailingDdRoomUsd: Number(hud.trailing_dd_room_usd ?? 0),
              trailingDdRoomPct: Number(hud.trailing_dd_room_pct ?? 0),
            });
          }
        } catch {
          // Ignore malformed frame
        }
      };
    } catch {
      // Fallback to HTTP snapshot polling if WebSocket unavailable
    }

    return () => {
      clearInterval(id);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [pollModule02Stream, selectedSymbol, streamPaused]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {
      all: listings.length,
      watchlist: watchlistSymbols.length,
      metals: 0,
      etfs: 0,
      bonds: 0,
      stocks: 0,
      futures: 0,
      fx: 0,
      crypto: 0,
    };
    for (const item of listings) {
      counts[item.category] = (counts[item.category] ?? 0) + 1;
    }
    return counts;
  }, [listings, watchlistSymbols.length]);

  const filteredListings = useMemo(() => {
    const q = searchQuery.trim().toUpperCase();
    return listings.filter((l) => {
      if (categoryFilter === "watchlist" && !watchlistSymbols.includes(l.symbol)) return false;
      if (openNowOnly && l.marketOpen !== true) return false;
      if (categoryFilter !== "all" && categoryFilter !== "watchlist" && l.category !== categoryFilter) {
        return false;
      }
      if (!q) return true;
      return (
        l.symbol.toUpperCase().includes(q) ||
        l.name.toUpperCase().includes(q) ||
        l.subCategory.toUpperCase().includes(q) ||
        l.venue.toUpperCase().includes(q) ||
        (l.isin && l.isin.toUpperCase().includes(q)) ||
        (l.issuer && l.issuer.toUpperCase().includes(q))
      );
    });
  }, [listings, categoryFilter, searchQuery, watchlistSymbols, openNowOnly]);

  const activeListing = useMemo(
    () => listings.find((l) => l.symbol === selectedSymbol) ?? listings[0],
    [listings, selectedSymbol]
  );

  const toggleWatchlist = useCallback((sym: string) => {
    setWatchlistSymbols((prev) =>
      prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym]
    );
  }, []);

  const toggleCompare = useCallback((sym: string) => {
    setCompareSymbols((prev) => {
      if (prev.includes(sym)) return prev.filter((s) => s !== sym);
      if (prev.length >= 6) return [...prev.slice(1), sym];
      return [...prev, sym];
    });
  }, []);

  useEffect(() => {
    const price = activeListing.price;
    const symbol = activeListing.symbol;
    const changed = fixtureSymbolRef.current !== symbol;
    fixtureSymbolRef.current = symbol;
    const stamp = new Date().toISOString();
    setFixtureTicks((prev) => {
      const history = changed ? [] : prev;
      const last = history[history.length - 1];
      if (last && Math.abs(last.close - price) < 1e-9) return history;
      const open = last?.close ?? price;
      return [
        ...history,
        {
          timestamp: stamp,
          open,
          high: Math.max(open, price),
          low: Math.min(open, price),
          close: price,
          volume: 1,
        },
      ].slice(-120);
    });
  }, [activeListing.symbol, activeListing.price]);

  const activeQuote = feedQuotes[activeListing.symbol];
  const activePriceFormatted = useMemo(() => {
    const raw = activeQuote?.price;
    if (typeof raw !== "number") return "No stored feed print";
    const native = activeListing.nativeCurrency ?? "USD";
    let converted = raw;
    if (native === "USD" && displayCurrency === "CAD") converted = raw * usdCadRate;
    if (native === "CAD" && displayCurrency === "USD") converted = raw / usdCadRate;
    return `${displayCurrency === "CAD" ? "CA$" : "US$"}${converted.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    })}`;
  }, [activeQuote, activeListing.nativeCurrency, displayCurrency, usdCadRate]);

  return (
    <div className="institutional-shell">
      {/* The page title and tabs live in the app frame; keep only this tab's live status. */}
      <div className="clean-toolrow" role="toolbar" aria-label="Catalog status">
        <span className="badge badge-emerald">Ring Buffer: {ringBufferSize.toLocaleString()} / 10,000</span>
      </div>

      <div className="clean-main-scroll" style={{ padding: "18px 24px" }}>
        {/* Precious Metals Spot & Unit Normalization Strip (Feature 2 & Feature 8) */}
        <div
          className="clean-card"
          style={{
            marginBottom: "14px",
            padding: "10px 16px",
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center", fontSize: "12.5px" }}>
            <span className="badge badge-blue">PRECIOUS METALS REFERENCE ({displayCurrency} / {metalSpotMatrix.unitLabel})</span>
            <span>
              <strong>Gold (XAU):</strong>{" "}
              <span className="mono-cell" style={{ color: "#FACC15" }}>
                {displayCurrency === "CAD" ? "CA$" : "$"}
                {metalSpotMatrix.gold.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </span>
            <span>
              <strong>Silver (XAG):</strong>{" "}
              <span className="mono-cell" style={{ color: "#E2E8F0" }}>
                {displayCurrency === "CAD" ? "CA$" : "$"}
                {metalSpotMatrix.silver.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </span>
            <span>
              <strong>Platinum (XPT):</strong>{" "}
              <span className="mono-cell" style={{ color: "#38BDF8" }}>
                {displayCurrency === "CAD" ? "CA$" : "$"}
                {metalSpotMatrix.platinum.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </span>
            <span>
              <strong>Palladium (XPD):</strong>{" "}
              <span className="mono-cell" style={{ color: "#A78BFA" }}>
                {displayCurrency === "CAD" ? "CA$" : "$"}
                {metalSpotMatrix.palladium.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </span>
            <span className="mono-cell" style={{ color: "#94A3B8", fontSize: "11.5px" }}>
              BoC USD/CAD: {usdCadRate.toFixed(4)}
            </span>
          </div>

          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <div className="seg" role="group" aria-label="Currency normalization">
              <button
                type="button"
                className={`clean-tf-btn ${displayCurrency === "USD" ? "active" : ""}`}
                style={{ padding: "5px 10px", fontSize: "12px" }}
                onClick={() => setDisplayCurrency("USD")}
              >
                USD ($)
              </button>
              <button
                type="button"
                className={`clean-tf-btn ${displayCurrency === "CAD" ? "active" : ""}`}
                style={{ padding: "5px 10px", fontSize: "12px" }}
                onClick={() => setDisplayCurrency("CAD")}
              >
                CAD (CA$)
              </button>
            </div>
            <div className="seg" role="group" aria-label="Precious metal unit normalization">
              <button
                type="button"
                className={`clean-tf-btn ${metalUnit === "troy_oz" ? "active" : ""}`}
                style={{ padding: "5px 10px", fontSize: "12px" }}
                onClick={() => setMetalUnit("troy_oz")}
              >
                troy oz
              </button>
              <button
                type="button"
                className={`clean-tf-btn ${metalUnit === "gram" ? "active" : ""}`}
                style={{ padding: "5px 10px", fontSize: "12px" }}
                onClick={() => setMetalUnit("gram")}
              >
                gram
              </button>
              <button
                type="button"
                className={`clean-tf-btn ${metalUnit === "kg" ? "active" : ""}`}
              style={{ padding: "5px 10px", fontSize: "12px" }}
                onClick={() => setMetalUnit("kg")}
              >
                kg
              </button>
            </div>
          </div>
        </div>

        {/* AI Daily Investment & ML Loop Brief (Yesterday vs Today + Conviction Ratings + ML Loop) */}
        <AiDailyInvestmentBriefPanel
          selectedSymbol={selectedSymbol}
          onSelectSymbol={setSelectedSymbol}
        />

        {/* Asset catalog toolbar */}
        <div className="asset-toolbar" style={{ flexWrap: "wrap", gap: "10px" }}>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "all" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => setCategoryFilter("all")}
            >
              <GuideIcon name="all" />
              All Authentic ({categoryCounts.all})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "metals" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("metals");
                setSelectedSymbol("GC");
              }}
            >
              <GuideIcon name="futures" color={categoryFilter === "metals" ? "#FFFFFF" : markColor("futures")} />
              Precious Metals ({categoryCounts.metals})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "etfs" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("etfs");
                setSelectedSymbol("SPY");
              }}
            >
              <GuideIcon name="equity" color={categoryFilter === "etfs" ? "#FFFFFF" : markColor("equity")} />
              ETFs &amp; Funds ({categoryCounts.etfs})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "bonds" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("bonds");
                setSelectedSymbol("TLT");
              }}
            >
              <GuideIcon name="equity" color={categoryFilter === "bonds" ? "#FFFFFF" : markColor("equity")} />
              Bonds &amp; T-Bills ({categoryCounts.bonds})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "stocks" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("stocks");
                setSelectedSymbol("NVDA");
              }}
            >
              <GuideIcon name="equity" color={categoryFilter === "stocks" ? "#FFFFFF" : markColor("equity")} />
              Public Equities ({categoryCounts.stocks})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "futures" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("futures");
                setSelectedSymbol("ES");
              }}
            >
              <GuideIcon name="futures" color={categoryFilter === "futures" ? "#FFFFFF" : markColor("futures")} />
              CME Futures ({categoryCounts.futures})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "fx" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("fx");
                setSelectedSymbol("EUR_USD");
              }}
            >
              <GuideIcon name="futures" color={categoryFilter === "fx" ? "#FFFFFF" : markColor("futures")} />
              Spot FX ({categoryCounts.fx})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "crypto" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("crypto");
                setSelectedSymbol("BTC-USD");
              }}
            >
              <GuideIcon name="crypto" color={categoryFilter === "crypto" ? "#FFFFFF" : markColor("crypto")} />
              Major Crypto ({categoryCounts.crypto})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${openNowOnly ? "active" : ""}`}
              aria-pressed={openNowOnly}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => setOpenNowOnly((on) => !on)}
            >
              Open now
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "watchlist" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => setCategoryFilter("watchlist")}
            >
              ★ Watchlist ({categoryCounts.watchlist})
            </button>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter ticker, ISIN, issuer, Gold, Silver, ETF, Bond..."
              aria-label="Filter authentic assets"
              style={{
                padding: "6px 12px",
                fontSize: "12.5px",
                borderRadius: "6px",
                border: "1px solid rgba(148, 163, 184, 0.28)",
                background: "rgba(15, 23, 42, 0.65)",
                color: "#F8FAFC",
                minWidth: "250px",
              }}
            />
            <div className="seg" role="group" aria-label="Catalog view">
              <button
                type="button"
                className={`clean-tf-btn ${catalogView === "cards" ? "active" : ""}`}
                aria-pressed={catalogView === "cards"}
                style={{ padding: "7px 12px", fontSize: "13px" }}
                onClick={() => setCatalogView("cards")}
              >
                Cards
              </button>
              <button
                type="button"
                className={`clean-tf-btn ${catalogView === "list" ? "active" : ""}`}
                aria-pressed={catalogView === "list"}
                style={{ padding: "7px 12px", fontSize: "13px" }}
                onClick={() => setCatalogView("list")}
              >
                List
              </button>
            </div>
          </div>
        </div>

        {sessionVenues.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", fontSize: 12.5, marginBottom: 8 }}>
            <span style={{ color: "#94A3B8" }}>Open now</span>
            {sessionVenues.filter((venue) => venue.is_open).map((venue) => (
              <button
                key={venue.venue_id}
                type="button"
                className="clean-tf-btn"
                style={{ padding: "4px 8px", fontSize: 12 }}
                onClick={() => {
                  if (!venue.look_symbol) return;
                  setCategoryFilter("all");
                  setSelectedSymbol(venue.look_symbol);
                }}
              >
                {venue.venue_name}
              </button>
            ))}
            <span style={{ color: "#94A3B8" }}>
              The research hand watches these clocks. The scored book is crypto 4h. Positions stay where they are.
            </span>
          </div>
        )}
        {activeListing.marketOpen === false && (
          <div style={{ fontSize: 12.5, color: "#F0803C", marginBottom: 8 }}>
            {activeListing.symbol} is {activeListing.marketLabel || "closed"} on {activeListing.marketName}.
            {activeListing.marketCountdown ? ` ${activeListing.marketCountdown}.` : ""}
            {" "}Choose an open market above to look there. This chart change leaves positions open.
          </div>
        )}

        {catalogView === "cards" ? (
          <div className="asset-grid">
            {filteredListings.map((item) => (
              <AssetCard
                key={item.symbol}
                symbol={item.symbol}
                name={item.name.replace(/ \(SEC CIK \d+\)$/, "")}
                kind={item.subCategory}
                venue={item.venue}
                market={item.marketName ? `${item.marketOpen ? "Open" : "Closed"} · ${item.marketName}` : undefined}
                marketOpen={item.marketOpen}
                quote={feedQuotes[item.symbol]}
                selected={item.symbol === selectedSymbol}
                onSelect={() => setSelectedSymbol(item.symbol)}
              />
            ))}
          </div>
        ) : (
          <AssetTable
            rows={filteredListings.map((i) => ({
              symbol: i.symbol,
              name: i.name.replace(/ \(SEC CIK \d+\)$/, ""),
              kind: i.subCategory,
              market: i.marketName ? `${i.marketOpen ? "Open" : "Closed"} · ${i.marketName}` : undefined,
              marketOpen: i.marketOpen,
            }))}
            quotes={feedQuotes}
            selected={selectedSymbol}
            onSelect={setSelectedSymbol}
          />
        )}

        {/* Selected Instrument Authenticity & Chart Inspector (Single DeskChart Invariant) */}
        <div className="clean-card selected-market-viewer">
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "space-between",
              gap: 10,
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              <strong>{activeListing.symbol} — {activeListing.name}</strong>
              {activeListing.marketName ? (
                <span className="asset-card-market" data-market-open={activeListing.marketOpen ? "1" : "0"}>
                  {activeListing.marketOpen ? "Open" : "Closed"} · {activeListing.marketName}
                  {activeListing.marketLabel ? ` · ${activeListing.marketLabel}` : ""}
                </span>
              ) : null}
              <span className="badge badge-emerald">AUTHENTICITY VERIFIED</span>
              {activeListing.isin && (
                <span className="badge badge-blue mono-cell">ISIN {activeListing.isin}</span>
              )}
              {activeListing.secCik && (
                <span className="badge badge-blue mono-cell">SEC CIK {activeListing.secCik}</span>
              )}
              {activeListing.exchangeMic && (
                <span className="badge badge-blue mono-cell">MIC {activeListing.exchangeMic}</span>
              )}
              <span className="mono-cell" style={{ fontSize: "13px", color: "#00F29D" }}>
                {activePriceFormatted}
              </span>
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className={`clean-tf-btn ${watchlistSymbols.includes(activeListing.symbol) ? "active" : ""}`}
                style={{ padding: "5px 10px", fontSize: "12px" }}
                onClick={() => toggleWatchlist(activeListing.symbol)}
              >
                {watchlistSymbols.includes(activeListing.symbol) ? "★ In Watchlist" : "☆ Pin Watchlist"}
              </button>
              <button
                type="button"
                className={`clean-tf-btn ${compareSymbols.includes(activeListing.symbol) ? "active" : ""}`}
                style={{ padding: "5px 10px", fontSize: "12px" }}
                onClick={() => toggleCompare(activeListing.symbol)}
              >
                {compareSymbols.includes(activeListing.symbol) ? "✓ In Compare" : "+ Add to Compare"}
              </button>
            </div>
          </div>

          {/* Provenance, Custody & Canadian NI 31-103 / NI 81-102 Metadata Strip */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "10px",
              marginBottom: "14px",
              padding: "10px 12px",
              borderRadius: "6px",
              background: "rgba(15, 23, 42, 0.55)",
              border: "1px solid rgba(148, 163, 184, 0.18)",
              fontSize: "12px",
            }}
          >
            <div>
              <div style={{ color: "#94A3B8" }}>Verified Issuer / Sponsor</div>
              <div style={{ color: "#F8FAFC", fontWeight: 600 }}>{activeListing.issuer}</div>
            </div>
            <div>
              <div style={{ color: "#94A3B8" }}>Custody / Holding Structure</div>
              <div style={{ color: "#F8FAFC" }}>{activeListing.custodyForm}</div>
            </div>
            <div>
              <div style={{ color: "#94A3B8" }}>MER / Expense Ratio &amp; Spread</div>
              <div className="mono-cell" style={{ color: "#F8FAFC" }}>
                {typeof activeListing.expenseRatioBps === "number"
                  ? `${activeListing.expenseRatioBps} bps (${(activeListing.expenseRatioBps / 100).toFixed(2)}% MER)`
                  : "Direct Contract / N/A"}{" "}
                · ~{activeListing.spreadBps.toFixed(1)} bps spread
              </div>
            </div>
            <div>
              <div style={{ color: "#94A3B8" }}>Source &amp; Regulatory Boundary</div>
              <div className="mono-cell" style={{ color: "#00C8FF" }}>
                {activeQuote?.source ?? "atlas_feed"} · {activeQuote?.status ?? "verified"} · safety_score: null
              </div>
            </div>
          </div>

          <DeskChart
            symbol={activeListing.symbol}
            modelSymbol={activeListing.symbol}
            timeframe={chartTimeframe}
            frameClassName="desk-chart-frame"
            onTimeframe={(tf) => {
              if (["1s", "1m", "5m", "15m", "1h", "1D"].includes(tf)) {
                setChartTimeframe(tf as typeof chartTimeframe);
              }
            }}
          />

          <div
            style={{
              marginTop: "10px",
              fontSize: "11.5px",
              color: "#94A3B8",
              lineHeight: 1.45,
            }}
          >
            <strong>Regulatory &amp; Authenticity Disclosure (CSA NI 31-103 / NI 81-102):</strong>{" "}
            {activeListing.disclosureNote} ATLAS is a non-custodial research and paper-simulation
            workspace (`execution_permission: none`). Instrument authenticity verification confirms
            official regulatory identifiers only and does not constitute personalized investment advice.
          </div>
        </div>

        {/* Side-by-Side Instrument Comparison Table (Feature 8 & Feature 9) */}
        <div className="clean-card" style={{ marginBottom: "16px", padding: "14px 18px" }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "8px",
              marginBottom: "10px",
            }}
          >
            <div>
              <strong style={{ fontSize: "14px", color: "#F8FAFC" }}>
                Side-by-Side Instrument Comparison ({compareSymbols.length} selected)
              </strong>
              <span style={{ marginLeft: "10px", fontSize: "12px", color: "#94A3B8" }}>
                Compare physical bullion ETPs, Crown Corp ETRs, futures, ETFs, and sovereign bonds across USD &amp; CAD
              </span>
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Instrument Name</th>
                  <th>Category</th>
                  <th>Issuer</th>
                  <th>ISIN / CIK</th>
                  <th>MIC</th>
                  <th>Price (USD)</th>
                  <th>Price (CAD)</th>
                  <th>MER (bps)</th>
                  <th>Holding / Custody Form</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {compareSymbols.map((sym) => {
                  const row = listings.find((l) => l.symbol === sym);
                  if (!row) return null;
                  const q = feedQuotes[sym];
                  const rawP = q?.price;
                  const native = row.nativeCurrency ?? "USD";
                  const pUsd =
                    typeof rawP === "number"
                      ? native === "CAD"
                        ? rawP / usdCadRate
                        : rawP
                      : null;
                  const pCad =
                    typeof rawP === "number"
                      ? native === "CAD"
                        ? rawP
                        : rawP * usdCadRate
                      : null;
                  return (
                    <tr
                      key={sym}
                      style={{ cursor: "pointer" }}
                      onClick={() => setSelectedSymbol(sym)}
                    >
                      <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                        {row.symbol}
                      </td>
                      <td>{row.name.replace(/ \(SEC CIK \d+\)$/, "")}</td>
                      <td>{row.subCategory}</td>
                      <td>{row.issuer}</td>
                      <td className="mono-cell">
                        {row.isin ?? (row.secCik ? `CIK ${row.secCik}` : "Exchange Native")}
                      </td>
                      <td className="mono-cell">{row.exchangeMic ?? "—"}</td>
                      <td className="mono-cell">
                        {pUsd !== null
                          ? `$${pUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                          : "—"}
                      </td>
                      <td className="mono-cell">
                        {pCad !== null
                          ? `CA$${pCad.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                          : "—"}
                      </td>
                      <td className="mono-cell">
                        {typeof row.expenseRatioBps === "number" ? `${row.expenseRatioBps} bps` : "0 / Futures"}
                      </td>
                      <td>{row.custodyForm}</td>
                      <td className="mono-cell">{q?.source ?? "verified_store"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Real-Time Remaining-Room HUD */}
        <div className="clean-kpi-row" style={{ marginBottom: "16px" }}>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Mark-to-Market Open Equity</span>
            <span className="clean-kpi-value">${remainingRoomHud.currentEquityUsd.toLocaleString()}</span>
            <span className="clean-kpi-sub" style={{ color: "#00F29D" }}>
              SOD ${remainingRoomHud.startOfDayUsd.toLocaleString()} · reference ${remainingRoomHud.referenceUsd.toLocaleString()}
            </span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Daily Loss Cushion ({remainingRoomHud.dailyLossLimitPct.toFixed(1)}%)</span>
            <span className="clean-kpi-value" style={{ color: "#00F29D" }}>
              ${remainingRoomHud.dailyLossRoomUsd.toLocaleString()}
            </span>
            <span className="clean-kpi-sub">
              {remainingRoomHud.dailyLossRoomPct.toFixed(2)}% buffer remaining before auto-flatten
            </span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">
              {remainingRoomHud.drawdownMode === "static" ? "Static" : "Trailing"} Drawdown Cushion ({remainingRoomHud.drawdownLimitPct.toFixed(1)}%)
            </span>
            <span className="clean-kpi-value" style={{ color: "#00C8FF" }}>
              ${remainingRoomHud.trailingDdRoomUsd.toLocaleString()}
            </span>
            <span className="clean-kpi-sub">
              {remainingRoomHud.trailingDdRoomPct.toFixed(2)}% buffer remaining above ${remainingRoomHud.trailingFloorUsd.toLocaleString()} floor
            </span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">500ms Feed Freshness Breaker</span>
            <span className="clean-kpi-value" style={{ color: "#00F29D" }}>
              {activeListing.latencyMs.toFixed(1)}ms
            </span>
            <span className="clean-kpi-sub">
              Competition freshness gate 500ms · fixture venue label {activeListing.provider}
            </span>
          </div>
        </div>

        <details className="ux-collapse">
          <summary>
            Desk context<span className="ux-collapse-hint">role, feed origin, ring buffer</span>
          </summary>
          <div className="ux-collapse-body">
            {/* RBAC Client Segment Selector Strip */}
            <div className="clean-card" style={{ marginBottom: "16px", padding: "14px 18px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
                <div style={{ minWidth: 0, width: "100%" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <span className="badge badge-blue">RBAC CLIENT SEGMENT SEGREGATION</span>
                    <strong style={{ fontSize: "14px", color: "#F8FAFC" }}>{profile.title}</strong>
                    <span className="mono-cell" style={{ fontSize: "11.5px", color: "#00F29D" }}>
                      execution_permission: {profile.executionPermission}
                    </span>
                  </div>
                  <div style={{ fontSize: "12px", color: "#94A3B8", marginTop: "4px" }}>{profile.focusSummary}</div>
                </div>

                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  {(Object.keys(CLIENT_ROLE_PROFILES) as ClientRoleId[]).map((rKey) => {
                    const rMeta = CLIENT_ROLE_PROFILES[rKey];
                    return (
                      <button
                        key={rKey}
                        type="button"
                        className={`clean-tf-btn ${role === rKey ? "active" : ""}`}
                        style={{ padding: "6px 12px", fontSize: "12px" }}
                        onClick={() => {
                          setRole(rKey);
                          setRbacBanner(
                            `Switched RBAC Client Context to '${rKey}' (${rMeta.title}) · execution_permission=${rMeta.executionPermission}`
                          );
                        }}
                      >
                        {rKey} · {rMeta.segment.split(" ")[0]}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div
                className="mono-cell"
                style={{
                  marginTop: "10px",
                  padding: "8px 12px",
                  borderRadius: "6px",
                  background: "#070A0F",
                  border: "1px solid rgba(0, 200, 255, 0.25)",
                  fontSize: "11.5px",
                  color: "#00C8FF",
                }}
              >
                {rbacBanner}
                <div style={{ marginTop: 4, color: "#94A3B8" }}>{feedNote}</div>
              </div>
            </div>

            <AssetMarkLegend />
          </div>
        </details>

        <p className="ux-collapse-hint" style={{ margin: "4px 0" }}>
          Watchlist scan (pivots, Fibonacci, zones, VWAP, volume profile): <NavLink to="markets.scan">Scan &amp; Pine</NavLink>.{" "}
          <a href={tradingViewUrl(activeListing.symbol)} target="_blank" rel="noopener noreferrer">
            Open {activeListing.symbol} in TradingView ↗
          </a>
        </p>
      </div>
    </div>
  );
}

export function Module02ListingsView() {
  return (
    <RoleProvider initialRole="prop_firm_admin">
      <Module02InnerWorkbench />
    </RoleProvider>
  );
}

export default Module02ListingsView;
