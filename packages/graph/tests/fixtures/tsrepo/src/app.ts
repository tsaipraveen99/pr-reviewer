import { fetchUser, Client } from "./api";
const c = new Client();
export function main() {
  fetchUser("1");
  c.get("/");
}
