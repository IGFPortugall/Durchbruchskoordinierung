// Zentrale Stelle für externe Bibliotheken.
// Die genauen Versionen stehen in der Import-Map in index.html.
export * as THREE from "three";
export * as OBC from "@thatopen/components";
export * as FRAGS from "@thatopen/fragments";

// web-ifc: JS-Modul und WASM müssen dieselbe Version haben.
export const WEB_IFC_WASM = "https://unpkg.com/web-ifc@0.0.77/";
