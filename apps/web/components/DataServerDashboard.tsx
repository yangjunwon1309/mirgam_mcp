"use client";

import { useEffect, useState } from "react";
import BeaconDataExplorer from "./BeaconDataExplorer";

type Node = { node_id: string; label: string; online: boolean; registered: boolean; farm_id?: string | null };
type Farm = { id: string; name: string };
type Props = { farmName: string; selectedNodeId: string | null; selectedSensorId: string | null; fetchProtected: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response> };

export default function DataServerDashboard({ farmName, selectedNodeId, selectedSensorId, fetchProtected }: Props) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [farms, setFarms] = useState<Farm[]>([]);
  const [farmId, setFarmId] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const [nodeResponse, farmResponse] = await Promise.all([
          fetchProtected("/api/backend/dashboard/beacons", { cache: "no-store" }),
          fetchProtected("/api/backend/api/v1/farms", { cache: "no-store" }),
        ]);
        if (!nodeResponse.ok || !farmResponse.ok) throw new Error("데이터 목록을 불러오지 못했습니다.");
        const nodeData = await nodeResponse.json();
        const farmData = await farmResponse.json();
        if (active) { setNodes(nodeData.nodes ?? []); setFarms(Array.isArray(farmData) ? farmData : []); setError(""); }
      } catch (err) { if (active) setError(err instanceof Error ? err.message : "데이터 목록을 불러오지 못했습니다."); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [fetchProtected]);
  return <div className="data-server-dashboard">
    <div className="data-server-controls"><label>농장 선택<select value={farmId} onChange={(event) => setFarmId(event.target.value)}><option value="">전체 농장</option>{farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.name}</option>)}</select></label><span>최근 수신 기록을 15초마다 갱신합니다.</span></div>
    {error && <p className="beacon-notice" role="status">{error}</p>}
    <BeaconDataExplorer key={`${farmId}:${selectedNodeId ?? ""}:${selectedSensorId ?? ""}`} farmId={farmId || null} farmName={farms.find((farm) => farm.id === farmId)?.name ?? farmName} nodes={nodes} fetchProtected={fetchProtected} initialNodeId={selectedNodeId} initialSensorId={selectedSensorId} />
  </div>;
}
