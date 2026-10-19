def context():
    return {'org_id':'eval','brand_revision':2,'passport':{
        'brand_name':'Field Bag','target_audience':'Daily commuters','campaign_language':'en',
        'tone':'Warm, concrete and brief','negative_constraints':['Never promise lifetime durability, free shipping, waterproofing, or discounts.'],
        'banned_terms':['indestructible'],'competitor_names':['Acme']},
        'sources':[{'id':'fact','org_id':'eval','revision':1,'kind':'product','external_id':'bag',
                    'content':'The bag uses reinforced stitching on the handles. It is not waterproof.'}],
        'products':[{'id':'bag','org_id':'eval','name':'Field Bag','revision':1}],
        'proof_points':[{'id':'handles','source_id':'fact','revision':1,'quote':'The bag uses reinforced stitching on the handles.',
                         'product_id':'bag','objection_topics':['durability'],'confirmed_by':'eval-owner','confirmed_at':'2026-10-19T00:00:00Z'}],
        'objections':[{'id':'buyer','org_id':'eval','inbound_id':'inbound','prospect_id':'buyer', 'product_id':'bag',
                       'topic':'durability','buyer_text':'Will the handles last on my daily commute?','created_at':'2026-10-19T00:00:00Z'}]}


def campaign():
    return {'schema_version':1,'trigger_reason':'Generated from 1 recent buyer conversation about durability',
        'target_persona':{'id':'default','name':'Daily commuters','description':'Daily commuters'},'language':'en',
        'hooks':[{'framework':'A','text':'Will the handles last on my daily commute?'},
                 {'framework':'B','text':'The bag uses reinforced stitching on the handles.'},
                 {'framework':'C','text':'DM us to ask about the Field Bag.'}],
        'video_script':[{'spoken_narration':'Worried about your bag handles? The bag uses reinforced stitching on the handles. DM us for details.',
                         'visual_broll_cues':'Close-up of the reinforced handle stitching on the Field Bag.','on_screen_text':'Reinforced handle stitching'}],
        'social_captions':{'instagram':'Handle worries on your commute? Ask us about the Field Bag.',
                           'telegram':'The bag uses reinforced stitching on the handles. DM us for details.',
                           'tiktok':'Will your bag handles last? Ask about the Field Bag.'},
        'buyer_quotes':[{'source_id':'buyer','text':'Will the handles last on my daily commute?'}],
        'proof_references':[{'source_id':'fact','revision':1,'quote':'The bag uses reinforced stitching on the handles.'}], 'brand_revision':2}
