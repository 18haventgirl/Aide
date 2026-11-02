import type { Note, PersonDataFilter, User } from './types';

export interface StoredConversation {
  id: number;
  id_str: string;
  user_id: number;
  title: string;
  description: string;
  status: 'active' | 'inactive' | 'archived';
  last_active: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface StoredMessage {
  id: number | string;
  content: string;
  sender_type: string;
  sender_id: string | null;
  created_at: string | null;
  extra_data?: unknown;
}

export interface UserList<T> {
  data: T[];
  total: number;
  user_id: number;
}

export type SearchNote = Note & { snippet?: string };
export interface NoteSearchRequest {
  query: string;
  tag?: string;
  status?: string;
  limit?: number;
  use_vector_search?: boolean;
}
export type ListParams = PersonDataFilter & { limit?: number; offset?: number };

export interface CurrentUserResponse {
  success: boolean;
  message?: string;
  user_info?: User;
  data?: User;
}
