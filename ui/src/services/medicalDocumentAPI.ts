import { apiClient } from './apiService';

export interface SourceLine {
  id: string; page: number; text: string; method: 'text' | 'pdf' | 'docx' | 'ocr'; confidence: number | null;
}
export interface MedicalField {
  label: string; value: string; evidence: SourceLine[]; status: 'missing' | 'extracted' | 'needs_review';
}
export interface MedicalDocumentSummary {
  id: string; filename: string; status: 'review' | 'confirmed';
  document_type: 'outpatient' | 'discharge' | 'unknown'; created_at: string | null; health_record_id: number | null;
}
export interface MedicalDocument extends MedicalDocumentSummary {
  result: { schema_version: string; document_type: MedicalDocumentSummary['document_type'];
    fields: Record<string, MedicalField>; warnings: string[]; source_lines: SourceLine[]; model: string; };
  reviewed: { fields: Record<string, string>; observed_date: string } | null;
}

const root = '/api/medical-documents';
export const medicalDocumentAPI = {
  async list(): Promise<MedicalDocumentSummary[]> {
    return (await apiClient.get(root)).data.data;
  },
  async get(id: string): Promise<MedicalDocument> {
    return (await apiClient.get(`${root}/${id}`)).data.data;
  },
  async parseText(text: string): Promise<MedicalDocument> {
    return (await apiClient.post(`${root}/parse-text`, { text }, { timeout: 180000 })).data.data;
  },
  async parseFile(file: File): Promise<MedicalDocument> {
    return (await apiClient.post(`${root}/parse-file`, file, {
      params: { filename: file.name }, timeout: 180000,
      headers: { 'Content-Type': 'application/octet-stream' },
    })).data.data;
  },
  async confirm(id: string, fields: Record<string, string>, observed_date: string): Promise<MedicalDocument> {
    return (await apiClient.post(`${root}/${id}/confirm`, { fields, observed_date })).data.data;
  },
  async remove(id: string): Promise<void> { await apiClient.delete(`${root}/${id}`); },
};
