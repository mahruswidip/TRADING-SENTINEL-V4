"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReplayClockState, ReplayScenario, ReplaySpeed, ReplayStatus } from "@/domain/replay";
import { getReplayCheckpoints } from "@/lib/replay";

export function useReplayController(scenario: ReplayScenario) {
  const checkpoints = useMemo(() => getReplayCheckpoints(scenario), [scenario]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [status, setStatus] = useState<ReplayStatus>("IDLE");
  const [speed, setSpeed] = useState<ReplaySpeed>(1);
  const lastIndex = Math.max(checkpoints.length - 1, 0);

  const pause = useCallback(() => setStatus((value) => value === "COMPLETE" ? value : "PAUSED"), []);
  const play = useCallback(() => {
    setCurrentIndex((index) => index >= lastIndex ? 0 : index);
    setStatus("PLAYING");
  }, [lastIndex]);
  const stepForward = useCallback(() => {
    setStatus("PAUSED");
    setCurrentIndex((index) => Math.min(index + 1, lastIndex));
  }, [lastIndex]);
  const stepBackward = useCallback(() => {
    setStatus("PAUSED");
    setCurrentIndex((index) => Math.max(index - 1, 0));
  }, []);
  const jumpToStart = useCallback(() => {
    setStatus("PAUSED");
    setCurrentIndex(0);
  }, []);
  const restart = useCallback(() => {
    setStatus("IDLE");
    setCurrentIndex(0);
  }, []);
  const jumpToTimestamp = useCallback((timestamp: number) => {
    setStatus("PAUSED");
    setCurrentIndex(Math.max(0, checkpoints.findIndex((checkpoint) => checkpoint >= timestamp)));
  }, [checkpoints]);

  useEffect(() => {
    if (status !== "PLAYING") return;
    const timer = window.setInterval(() => {
      setCurrentIndex((index) => {
        if (index >= lastIndex) {
          setStatus("COMPLETE");
          return index;
        }
        return index + 1;
      });
    }, Math.max(50, 1000 / speed));
    return () => window.clearInterval(timer);
  }, [lastIndex, speed, status]);

  const currentTimestamp = checkpoints[currentIndex] ?? scenario.startTimestamp;
  const clock: ReplayClockState = {
    status,
    speed,
    currentTimestamp,
    startTimestamp: scenario.startTimestamp,
    endTimestamp: scenario.endTimestamp,
    currentIndex,
    totalSteps: checkpoints.length,
    isPlaying: status === "PLAYING",
  };

  return { clock, play, pause, stepForward, stepBackward, jumpToStart, jumpToTimestamp, restart, setSpeed };
}
