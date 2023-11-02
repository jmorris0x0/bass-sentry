Sub-Bass: 20 Hz - 60 Hz

This range includes the lowest frequencies that humans can perceive. Sounds in this range are often felt as vibrations rather than clearly heard.

Bass: 60 Hz - 250 Hz

This range covers the fundamental frequencies of many musical instruments and encompasses much of the "boominess" people associate with bass.


from(bucket: "mybucket")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "dBFS")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")


Use this to create a new password for greylog:

echo -n yourpassword | shasum -a 256




"""
Data Structure:
{
    "data_type": string,  # Either "audio_chunk" or "scalar"
    "timestamp": int, # Epoch
    "time_precision": string, # Either ns, us, ms, s
    "data": list or float,  # np.ndarray for "audio_chunk" and float for "scalar"
    "metadata": {
        "sample_rate": int,  # Required if "audio_chunk"
        "bit_depth": int,  # Required if "audio_chunk"
        "filter_low": int,  # Optional
        "filter_high": int,  # Optional
        "units": str  # Required if "scalar"
        "tags": list # Optional
        "location": str # Required

    }
}
"""




TODO:
Sometimes the remote node just goes no route to host and won't fix until reboot.
Support mutiple fields?
zeroconf ntp:
https://chat.openai.com/share/823fe7f0-0488-492a-9baa-5d95731e490c
Fix it so that the location comes from the config file and finds its way all to the end.






