import { redirect } from "next/navigation";

export default function ConnectChannelsRedirect() {
  redirect("/settings/channels");
}
