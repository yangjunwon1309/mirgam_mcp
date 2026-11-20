"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createBeaconApi } from "./api";
import { BeaconApiContext } from "./api-context";
import type { AddDraft, BeaconNode, Farm, Location, NodesResponse } from "./types";
import { usePolling } from "./hooks/usePolling";
import { usePendingDeletes } from "./hooks/usePendingDeletes";
import { useToasts } from "./ui/Toasts";

export type DashboardTab = "farm" | "jeju-weather" | "data-server" | "beacon";
type FleetContextValue = {
  api: ReturnType<typeof createBeaconApi>;
  farms: Farm[]; farmId: string | null; farm: Farm | null; hasBoundary: boolean; setFarmId(id: string | null): void; reloadFarms(): Promise<void>;
  allNodes: BeaconNode[]; nodes: BeaconNode[]; discoverable: BeaconNode[]; reachable: boolean | null; error: string | null; lastSyncAt: number | null; refreshNodes(): void;
  openDeviceId: string | null; openDevice(id: string): void; closeDevice(): void; highlightId: string | null; markHighlight(id: string): void;
  addDraft: AddDraft | null; openAdd(): void; openEdit(nodeId: string): void; updateDraft(p: Partial<AddDraft>): void; closeAdd(): void;
  placement: { nodeId: string } | null; beginPlacement(): void; completePlacement(nodeId: string, point: [number, number]): void; cancelPlacement(): void;
  dataSelection: { nodeId: string; sensorId?: string } | null; openData(nodeId: string, sensorId?: string): void;
  pendingDeletes: ReturnType<typeof usePendingDeletes>;
};
const FleetContext = createContext<FleetContextValue | null>(null);
type Props = { fetchProtected: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>; activeTab: DashboardTab; onNavigate(tab: DashboardTab): void; children: ReactNode };
const emptyLocation: Location = { site: null, zone: null, row: null, position: null, latitude: null, longitude: null };
function newDraft(): AddDraft { return { mode: "add", step: 1, nodeId: null, label: "", intervalS: 300, sensor: true, image: false, location: { ...emptyLocation }, metadata: { schema_version: 1, location: { ...emptyLocation }, sensors: [] } }; }
function parseNodeList(response: NodesResponse): BeaconNode[] {
  if (!Array.isArray(response.nodes)) throw new Error("Beacon 노드 목록 형식이 올바르지 않습니다.");
  return response.nodes.filter((node) => typeof node.node_id === "string");
}
export function BeaconFleetProvider({ fetchProtected, activeTab, onNavigate, children }: Props) {
  const api = useMemo(() => createBeaconApi(fetchProtected), [fetchProtected]);
  const toasts = useToasts();
  const [farms, setFarms] = useState<Farm[]>([]);
  const [farmIdState, setFarmIdState] = useState<string | null>(null);
  const initialFarmLoaded = useRef(false);
  const [allNodes, setAllNodes] = useState<BeaconNode[]>([]);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);
  const [openDeviceId, setOpenDeviceId] = useState<string | null>(null);
  const [addDraft, setAddDraft] = useState<AddDraft | null>(null);
  const [placement, setPlacement] = useState<{ nodeId: string } | null>(null);
  const [dataSelection, setDataSelection] = useState<{ nodeId: string; sensorId?: string } | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const highlightedTimer = useRef<number | undefined>(undefined);
  const warnedIds = useRef(new Set<string>());
  const farmId = farmIdState;
  const setFarmId = useCallback((id: string | null) => {
    setFarmIdState(id);
    try { sessionStorage.setItem("mirgam.beacon.ui", JSON.stringify({ farmId: id })); } catch { /* Storage may be unavailable. */ }
  }, []);
  const reloadFarms = useCallback(async () => {
    const loaded = await api.listFarms();
    setFarms(loaded);
    setFarmIdState((current) => {
      if (!initialFarmLoaded.current) {
        initialFarmLoaded.current = true;
        let stored: string | null = null;
        try { stored = (JSON.parse(sessionStorage.getItem("mirgam.beacon.ui") ?? "{}") as { farmId?: string }).farmId ?? null; } catch { stored = null; }
        if (stored && loaded.some((farm) => farm.id === stored)) return stored;
        return loaded[0]?.id ?? null;
      }
      return current && !loaded.some((farm) => farm.id === current) ? loaded[0]?.id ?? null : current;
    });
  }, [api]);
  useEffect(() => { void reloadFarms().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "농장 목록을 불러오지 못했습니다.")); }, [reloadFarms]);
  useEffect(() => {
    if (initialFarmLoaded.current) {
      try { sessionStorage.setItem("mirgam.beacon.ui", JSON.stringify({ farmId })); } catch { /* Storage may be unavailable. */ }
    }
  }, [farmId]);
  const farm = farms.find((item) => item.id === farmId) ?? null;
  const task = useCallback(async (signal: AbortSignal) => {
    try {
      const result = await api.listNodes(signal);
      const valid = parseNodeList(result).filter((node) => {
        if (/^tc-[0-9a-f]{6}$/.test(node.node_id)) return true;
        if (!warnedIds.current.has(node.node_id)) { warnedIds.current.add(node.node_id); console.warn("Invalid Beacon node ID omitted:", node.node_id); }
        return false;
      });
      setAllNodes(valid); setReachable(result.reachable); setError(result.error ?? null); setLastSyncAt(Date.now() / 1000);
    } catch (cause) {
      setReachable(false); setError(cause instanceof Error ? cause.message : "Beacon 서버에 연결할 수 없습니다."); throw cause;
    }
  }, [api]);
  const polling = usePolling(task, { intervalMs: activeTab === "farm" ? 30000 : 10000, enabled: activeTab !== "jeju-weather", deps: [activeTab] });
  const refreshNodes = polling.refresh;
  const nodes = useMemo(() => allNodes.filter((node) => node.registered && node.farm_id === farmId), [allNodes, farmId]);
  const discoverable = useMemo(() => allNodes.filter((node) => !node.registered), [allNodes]);
  const openDevice = useCallback((id: string) => setOpenDeviceId(id), []);
  const closeDevice = useCallback(() => setOpenDeviceId(null), []);
  const openAdd = useCallback(() => setAddDraft(newDraft()), []);
  const openEdit = useCallback((nodeId: string) => {
    const node = allNodes.find((item) => item.node_id === nodeId);
    if (!node) return;
    setAddDraft({ mode: "edit", step: 2, nodeId, label: node.label, intervalS: node.interval_s, sensor: node.requested_data.includes("sensor"), image: node.requested_data.includes("image"), location: { ...emptyLocation, ...(node.metadata.location ?? {}) }, metadata: node.metadata });
  }, [allNodes]);
  const updateDraft = useCallback((patch: Partial<AddDraft>) => setAddDraft((current) => current ? { ...current, ...patch } : current), []);
  const closeAdd = useCallback(() => { setAddDraft(null); setPlacement(null); }, []);
  const beginPlacement = useCallback(() => { if (addDraft?.nodeId) { setPlacement({ nodeId: addDraft.nodeId }); onNavigate("farm"); } }, [addDraft, onNavigate]);
  const completePlacement = useCallback((nodeId: string, point: [number, number]) => {
    setAddDraft((current) => current ? { ...current, nodeId, step: 3, location: { ...current.location, longitude: point[0], latitude: point[1] }, metadata: { ...current.metadata, location: { ...current.location, longitude: point[0], latitude: point[1] } } } : current);
    setPlacement(null); onNavigate("beacon");
  }, [onNavigate]);
  const cancelPlacement = useCallback(() => { setPlacement(null); setAddDraft((current) => current ? { ...current, step: 3 } : current); onNavigate("beacon"); }, [onNavigate]);
  const openData = useCallback((nodeId: string, sensorId?: string) => {
    setDataSelection({ nodeId, sensorId }); setOpenDeviceId(null); onNavigate("data-server");
  }, [onNavigate]);
  useEffect(() => { setOpenDeviceId(null); setAddDraft(null); setPlacement(null); }, [farmId]);
  useEffect(() => {
    if (!highlightId) return;
    highlightedTimer.current = window.setTimeout(() => setHighlightId(null), 2000);
    return () => { if (highlightedTimer.current !== undefined) window.clearTimeout(highlightedTimer.current); };
  }, [highlightId]);
  const markHighlight = useCallback((id: string) => setHighlightId(id), []);
  const pendingDeletes = usePendingDeletes(api, toasts, refreshNodes);
  const value = useMemo<FleetContextValue>(() => ({
    api, farms, farmId, farm, hasBoundary: Boolean(farm?.latest_boundary), setFarmId, reloadFarms,
    allNodes, nodes, discoverable, reachable, error, lastSyncAt, refreshNodes,
    openDeviceId, openDevice, closeDevice, highlightId,
    addDraft, openAdd, openEdit, updateDraft, closeAdd,
    placement, beginPlacement, completePlacement, cancelPlacement,
    dataSelection, openData, pendingDeletes, markHighlight,
  }), [api, farms, farmId, farm, setFarmId, reloadFarms, allNodes, nodes, discoverable, reachable, error, lastSyncAt, refreshNodes, openDeviceId, openDevice, closeDevice, highlightId, addDraft, openAdd, openEdit, updateDraft, closeAdd, placement, beginPlacement, completePlacement, cancelPlacement, dataSelection, openData, pendingDeletes, markHighlight]);
  return <BeaconApiContext.Provider value={api}><FleetContext.Provider value={value}>{children}</FleetContext.Provider></BeaconApiContext.Provider>;
}
export function useBeaconFleet(): FleetContextValue {
  const value = useContext(FleetContext);
  if (!value) throw new Error("BeaconFleetProvider가 필요합니다.");
  return value;
}
