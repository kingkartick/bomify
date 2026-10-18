import { CompanyAddress } from "@/features/settings/api";

/** Address block for document headers; nudges towards Settings when nothing is filled in. */
export default function CompanyAddressLines({ address }: { address: CompanyAddress }) {
    const cityLine = [address.city, address.state && `(${address.state})`].filter(Boolean).join(" ");
    const countryLine = [address.country, address.pincode].filter(Boolean).join(" - ");
    if (!address.line1 && !address.city && !address.pincode) {
        return <span className="text-gray-400">Address not set — add it in Settings → Company Profile</span>;
    }
    return (
        <>
            {address.line1 && <>{address.line1}<br /></>}
            {address.line2 && <>{address.line2}<br /></>}
            {cityLine && <>{cityLine}<br /></>}
            {countryLine}
        </>
    );
}
