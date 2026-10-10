export function isGmailAddress(value: string): boolean {
  return /^[^@\s]+@gmail\.com$/i.test(value.trim());
}
