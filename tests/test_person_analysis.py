import unittest
from person_analysis import Tracker,settings

def row(x=.2,confidence=.9):return {'kind':'person','confidence':confidence,'box':[x,.1,x+.2,.9]}

class PersonAnalysisTests(unittest.TestCase):
    def test_same_person_is_not_reannounced_and_new_appearance_is(self):
        tracker=Tracker();config=settings()
        self.assertEqual(tracker.update([row()],100,config)['reasons'],['presence'])
        self.assertEqual(tracker.update([row(.21)],101,config)['reasons'],[])
        self.assertEqual(tracker.update([row(.22)],110,config)['reasons'],['presence'])

    def test_line_hysteresis_and_permanence_are_distinct_events(self):
        tracker=Tracker();config=settings({'line_enabled':True,'dwell_seconds':10})
        tracker.update([row(.25)],100,config)
        tracker.update([row(.33)],101,config)
        tracker.update([row(.42)],102,config)
        crossed=tracker.update([row(.48)],103,config)
        self.assertEqual(crossed['reasons'],['line_positive'])
        for now in range(104,111):event=tracker.update([row(.48)],now,config)
        self.assertEqual(event['reasons'],['dwell'])
        self.assertEqual(tracker.update([row(.48)],111,config)['reasons'],[])

    def test_confirmation_and_bad_settings(self):
        tracker=Tracker();config=settings()
        self.assertFalse(tracker.update([row(confidence=.6)],100,config)['reasons'])
        self.assertEqual(tracker.update([row(confidence=.6)],101,config)['reasons'],['presence'])
        for bad in ({'confidence':float('nan')},{'line_axis':'z'},{'zone':[]}):
            with self.assertRaises(ValueError):settings(bad)
