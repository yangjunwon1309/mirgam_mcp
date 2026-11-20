"use client";
import { createContext, useContext } from "react";
import type { createBeaconApi } from "./api";
export type BeaconApi = ReturnType<typeof createBeaconApi>;
export const BeaconApiContext = createContext<BeaconApi | null>(null);
export function useBeaconApi(): BeaconApi {
  const api = useContext(BeaconApiContext);
  if (!api) throw new Error("BeaconFleetProvider가 필요합니다.");
  return api;
}
