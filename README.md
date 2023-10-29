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

