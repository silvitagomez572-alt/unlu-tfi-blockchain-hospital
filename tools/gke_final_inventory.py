"""Read-only retained-image inventory after verified runtime destruction."""
import json
from datetime import datetime,timezone
import gke_runtime as g

if __name__=='__main__':
    cleanup=json.loads((g.OUT/'CLEANUP.json').read_text());assert cleanup['status']=='PASS'
    images=g.gc('remaining-artifact-images',['artifacts','docker','images','list',
        'us-central1-docker.pkg.dev/'+g.PROJECT+'/hisjb-tfi','--include-tags'])
    g.save('RESIDUAL_COST_STATUS.json',{'utc':datetime.now(timezone.utc).isoformat(),
        'runtime_cleanup_verified':True,'retained_registry':'hisjb-tfi','retained_images':images,
        'approved_total_usd':3,'initial_two_hour_estimate_usd':0.5901,'actual_settled_charge_usd':None,
        'actual_charge_status':'NOT AVAILABLE: billing transaction/settled usage report not retrieved; estimate is not an invoice',
        'residual_upper_estimate_usd_month':0.05,'residual_basis':'Previously approved bound: at most 0.5 GiB at USD0.10/GiB-month, before free quota and taxes',
        'project_apis_budget_oidc_retained':True,'no_new_deployment':True})
