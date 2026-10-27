const paths: Record<string, string> = {
  search: 'm21 21-4.5-4.5M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  database: 'M20 6c0 2.2-3.6 4-8 4s-8-1.8-8-4 3.6-4 8-4 8 1.8 8 4ZM4 6v6c0 2.2 3.6 4 8 4s8-1.8 8-4V6M4 12v6c0 2.2 3.6 4 8 4s8-1.8 8-4v-6',
  chart: 'M4 3v18h17M9 17v-5M14 17V7M19 17V3',
  history: 'M3 11a9 9 0 1 1 2.5 7M3 3v8h8M12 7v5l3 2',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  chevron: 'm8 4 8 8-8 8',
  clock: 'M12 8v4l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  image: 'M3 3h18v18H3zM3 16l5-5 4 4 4-5 5 7M8 7h.01',
  text: 'M4 5h16M12 5v14M8 19h8',
  audio: 'M4 9v6M8 5v14M12 2v20M16 5v14M20 9v6',
  layers: 'm12 3 10 6-10 6L2 9zm-10 12 10 6 10-6M2 12l10 6 10-6',
  temporal: 'M3 7h7v10H3zM14 7h7v10h-7zM10 12h4m-2-2 2 2-2 2',
  filter: 'M4 6h16M7 12h10M10 18h4',
  check: 'm5 12 4 4L19 6',
  close: 'm6 6 12 12M6 18 18 6',
  plus: 'M12 5v14M5 12h14',
  bookmark: 'M6 3h12v18l-6-4-6 4z',
  play: 'm8 5 11 7-11 7z',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 14v7h16v-7',
  refresh: 'M20 4v6h-6M4 20v-6h6M4 9a8 8 0 0 1 14-5l2 6M4 14l2 6a8 8 0 0 0 14-5',
  info: 'M12 11v6M12 7h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  send: 'm3 3 19 9-19 9 4-9zm4 9h15',
  code: 'm8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16',
  menu: 'M3 6h18M3 12h18M3 18h18',
  folder: 'M3 6h7l2 3h9v12H3z',
};

/** Bộ biểu tượng SVG nhẹ, được ẩn khỏi trình đọc màn hình khi có nhãn chữ. */
export function Icon({ name, size = 20, className = '' }: { name: string; size?: number; className?: string }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.info} /></svg>;
}
