// Stable public route paths. Distinct, non-empty strings so the auth layer can hand
// back a redirect target without importing any Next.js machinery (keeps lib pure).
export const routes = {
  login: '/login',
  boardsList: '/boards',
  board(boardId: string): string {
    return `/boards/${boardId}`
  },
}
