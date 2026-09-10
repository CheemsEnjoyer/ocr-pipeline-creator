"use client";
import { useState } from "react";
import PipelineEditor from "@/components/PipelineEditor";

export default function Home() {
  const [instance, setInstance] = useState(0);
  return <PipelineEditor key={instance} onCreateNew={() => setInstance((value) => value + 1)}/>;
}
