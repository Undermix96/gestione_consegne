/**
 * api.js — Comunicazione REST con il server
 *
 * Ogni funzione corrisponde a un endpoint specifico.
 * Aggiunge automaticamente X-Session-Token.
 * Intercetta 401 → reindirizza al login.
 */

import { API } from './store.js';
import { getAuthHeaders, handleUnauthorized } from './auth.js';

async function _fetch(url, options = {}) {
  const r = await fetch(url, {
    ...options,
    headers: { ...getAuthHeaders(), ...(options.headers || {}) },
  });
  if (r.status === 401) {
    handleUnauthorized();
    throw new Error('Non autenticato');
  }
  return r;
}

async function _json(url, options = {}) {
  const r = await _fetch(url, options);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    throw Object.assign(new Error(err.error || 'Errore server'), { status: r.status, data: err });
  }
  return r.json();
}

// ── Auth ─────────────────────────────────────────

export async function pingServer() {
  const r = await _fetch(`${API}/ping`, { cache: 'no-store' });
  if (!r.ok) throw new Error('Ping fallito');
  return r.json();
}

// ── Stato (polling) ──────────────────────────────

export async function fetchStato() {
  return _json(`${API}/stato`, { cache: 'no-store' });
}

// ── Negozi ───────────────────────────────────────

export async function fetchNegozi() {
  return _json(`${API}/negozi`, { cache: 'no-store' });
}

export async function createNegozio(nome) {
  return _json(`${API}/negozi`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nome }),
  });
}

export async function updateNegozio(id, nome) {
  return _json(`${API}/negozi/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nome }),
  });
}

export async function deleteNegozio(id) {
  return _json(`${API}/negozi/${id}`, { method: 'DELETE' });
}

// ── Tipi account ─────────────────────────────────

export async function fetchTipiAccount() {
  return _json(`${API}/tipi-account`, { cache: 'no-store' });
}

export async function createTipoAccount(nome, permessi) {
  return _json(`${API}/tipi-account`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nome, permessi }),
  });
}

export async function updateTipoAccount(id, payload) {
  return _json(`${API}/tipi-account/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteTipoAccount(id) {
  return _json(`${API}/tipi-account/${id}`, { method: 'DELETE' });
}

// ── Utenti ───────────────────────────────────────

export async function fetchUtenti() {
  return _json(`${API}/utenti`, { cache: 'no-store' });
}

export async function createUtente(payload) {
  return _json(`${API}/utenti`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function setPasswordUtente(userId, nuova_hash) {
  return _json(`${API}/utenti/${userId}/password`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nuova_hash }),
  });
}

export async function setTipoAccount(userId, tipo_account_id) {
  return _json(`${API}/utenti/${userId}/tipo`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tipo_account_id }),
  });
}

export async function deleteUtente(userId) {
  return _json(`${API}/utenti/${userId}`, { method: 'DELETE' });
}

// ── Consegne ─────────────────────────────────────

export async function fetchConsegne() {
  return _json(`${API}/consegne`, { cache: 'no-store' });
}

export async function createConsegna(payload) {
  return _json(`${API}/consegne`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function updateConsegna(id, payload) {
  return _json(`${API}/consegne/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteConsegna(id) {
  return _json(`${API}/consegne/${id}`, { method: 'DELETE' });
}

// ── Giornate ─────────────────────────────────────

export async function fetchGiornate() {
  return _json(`${API}/giornate`, { cache: 'no-store' });
}

export async function createGiornata(payload) {
  return _json(`${API}/giornate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteGiornata(id) {
  return _json(`${API}/giornate/${id}`, { method: 'DELETE' });
}

export async function assegnaConsegne(gid, consegna_ids) {
  return _json(`${API}/giornate/${gid}/assegna`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consegna_ids }),
  });
}

export async function rimuoviConsegna(gid, cid) {
  return _json(`${API}/giornate/${gid}/assegna/${cid}`, { method: 'DELETE' });
}

export async function riordinaGiornata(gid, consegna_ids) {
  return _json(`${API}/giornate/${gid}/riordina`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consegna_ids }),
  });
}

export async function segnaCompletata(gid, cid) {
  return _json(`${API}/giornate/${gid}/consegne/${cid}/completa`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}

// ── Squadre ──────────────────────────────────────

export async function fetchSquadre() {
  return _json(`${API}/squadre`, { cache: 'no-store' });
}

export async function createSquadra(nome) {
  return _json(`${API}/squadre`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nome }),
  });
}

export async function updateSquadra(id, payload) {
  return _json(`${API}/squadre/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteSquadra(id) {
  return _json(`${API}/squadre/${id}`, { method: 'DELETE' });
}
