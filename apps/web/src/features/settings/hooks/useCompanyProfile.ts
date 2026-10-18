import { useEffect, useState } from "react";
import { settingsApi, CompanyProfile } from "@/features/settings/api";

const EMPTY_PROFILE: CompanyProfile = {
    name: "",
    gstin: "",
    address: { line1: "", line2: "", city: "", state: "", pincode: "", country: "India" },
};

// Shared across pages so the profile is fetched once per page load
let cached: Promise<CompanyProfile> | null = null;

/** The company details entered in Settings → Company Profile. */
export function useCompanyProfile(): { profile: CompanyProfile; loaded: boolean } {
    const [profile, setProfile] = useState<CompanyProfile>(EMPTY_PROFILE);
    const [loaded, setLoaded] = useState(false);

    useEffect(() => {
        let active = true;
        cached ??= settingsApi.getCompanyProfile().catch(() => {
            cached = null;
            return EMPTY_PROFILE;
        });
        cached.then((p) => {
            if (active) {
                setProfile(p);
                setLoaded(true);
            }
        });
        return () => {
            active = false;
        };
    }, []);

    return { profile, loaded };
}

/** Call after saving Settings so pages pick up the new details. */
export function invalidateCompanyProfile() {
    cached = null;
}
