import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import Index from "./pages/Index.tsx";
import NewTrip from "./pages/NewTrip.tsx";
import TripShape from "./pages/TripShape.tsx";
import FlightsFlow from "./pages/FlightsFlow.tsx";
import Stays from "./pages/Stays.tsx";
import Cars from "./pages/Cars.tsx";
import Do from "./pages/Do.tsx";
import Timeline from "./pages/Timeline.tsx";
import Settings from "./pages/Settings.tsx";
import NotFound from "./pages/NotFound.tsx";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/new" element={<NewTrip />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/trip/:tripId/shape" element={<TripShape />} />
          <Route path="/trip/:tripId/flights" element={<FlightsFlow />} />
          <Route path="/trip/:tripId/stays" element={<Stays />} />
          <Route path="/trip/:tripId/cars" element={<Cars />} />
          <Route path="/trip/:tripId/do" element={<Do />} />
          <Route path="/trip/:tripId/timeline" element={<Timeline />} />
          {/* legacy static routes kept for dev convenience */}
          <Route path="/trip/shape" element={<TripShape />} />
          <Route path="/trip/timeline" element={<Timeline />} />
          {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
