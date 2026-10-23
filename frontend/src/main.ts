import { createApp } from "vue";
import App from "./App.vue";
import { setFailureHandler } from "./lib/api";
import { raise } from "./lib/attention";
import { router } from "./router";
import "./styles.css";

setFailureHandler(raise); // a failed write that names its problems: a dialog, or the page goes to the place

createApp(App).use(router).mount("#app");
