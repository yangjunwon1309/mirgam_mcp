import type { BeaconDetail, ConfigureBody, DeleteRequest, DeleteResponse, Energy, Farm, NodesResponse, UsbPort } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}
type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type JsonObject = Record<string, unknown>;
function detailMessage(body: unknown): string {
  if (typeof body !== "object" || body === null) return "요청을 완료하지 못했습니다.";
  const detail = (body as JsonObject).detail;
  if (typeof detail === "string") return detail;
  if (typeof detail === "object" && detail !== null && typeof (detail as JsonObject).message === "string") return (detail as JsonObject).message as string;
  return "요청을 완료하지 못했습니다.";
}
async function request<T>(fetchProtected: Fetch, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetchProtected(path, { ...init, cache: "no-store" });
  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try { body = JSON.parse(text) as unknown; }
    catch { body = text; }
  }
  if (!response.ok) throw new ApiError(response.status, detailMessage(body), body);
  return body as T;
}
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}
export function createBeaconApi(fetchProtected: Fetch) {
  return {
    listNodes(signal?: AbortSignal): Promise<NodesResponse> {
      return request(fetchProtected, "/api/backend/dashboard/beacons", { signal });
    },
    getNode(id: string, signal?: AbortSignal): Promise<BeaconDetail> {
      return request(fetchProtected, "/api/backend/dashboard/beacons/" + encodeURIComponent(id), { signal });
    },
    getEnergy(id: string, signal?: AbortSignal): Promise<Energy> {
      return request(fetchProtected, "/api/backend/dashboard/beacons/" + encodeURIComponent(id) + "/energy", { signal });
    },
    listUsb(): Promise<{ reachable: boolean; ports: UsbPort[] }> {
      return request(fetchProtected, "/api/backend/dashboard/beacons/usb");
    },
    resetUsb(port: string): Promise<unknown> {
      return request(fetchProtected, "/api/backend/dashboard/beacons/usb/" + encodeURIComponent(port) + "/reset", json("POST", {}));
    },
    configure(id: string, body: ConfigureBody): Promise<unknown> {
      return request(fetchProtected, "/api/backend/dashboard/beacons/" + encodeURIComponent(id) + "/configure", json("PUT", body));
    },
    action(id: string, name: "detach" | "watch" | "session" | "hibernate", body: object): Promise<unknown> {
      return request(fetchProtected, "/api/backend/dashboard/beacons/" + encodeURIComponent(id) + "/actions/" + name, json("POST", body));
    },
    async command(id: string, body: { type: "sensor" | "image"; fs?: string; q?: number; warm?: number }): Promise<{ command_id: number }> {
      const result = await request<{ command_id?: number }>(fetchProtected, "/api/backend/dashboard/beacons/" + encodeURIComponent(id) + "/commands", json("POST", body));
      if (typeof result.command_id !== "number") throw new ApiError(500, "명령 번호를 받지 못했습니다.", result);
      return { command_id: result.command_id };
    },
    deleteData(id: string, body: DeleteRequest, signal?: AbortSignal): Promise<DeleteResponse> {
      return request(fetchProtected, "/api/backend/dashboard/beacons/" + encodeURIComponent(id) + "/data/delete", { ...json("POST", body), signal });
    },
    listFarms(): Promise<Farm[]> {
      return request(fetchProtected, "/api/backend/api/v1/farms");
    },
  };
}
