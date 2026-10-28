// HydraNest: a phone's remote (Tailscale) address.
import { devicePath, request } from './client';

/** off: no address; waiting: not tried yet; attached: reachable over the
 *  network (at home over Wi-Fi, or through Tailscale); failed: see error. */
export type RemoteState = 'off' | 'waiting' | 'attached' | 'failed';

export interface RemoteAccess {
  address: string;
  state: RemoteState;
  /** An error-text code: remote_unreachable, remote_not_added, ... */
  error?: string;
  /** The address last tried, or where the muxer sees the phone. */
  ip?: string;
  checkedAt?: string;
}

export function getRemoteAccess(udid: string, signal?: AbortSignal): Promise<RemoteAccess> {
  return request<RemoteAccess>(`${devicePath(udid)}/remote`, { signal });
}

/** An empty address turns remote access off. */
export function setRemoteAddress(udid: string, address: string, signal?: AbortSignal): Promise<RemoteAccess> {
  return request<RemoteAccess>(`${devicePath(udid)}/remote`, { method: 'PUT', body: { address }, signal });
}
